import base64
import json
import os
from typing import Any, Optional

import kubernetes.client
from kubernetes import client
from kubernetes.client import V1ConfigMap

from .chat import Chat


class State:
    def __init__(self, initial_state: dict[str, Any]):
        self.state = initial_state
        self.bot = None
        self.changed = False

    def initialize(self, bot):
        self.state.update(self.read())

    def read(self) -> dict[str, Any]:
        raise NotImplemented

    def write(self):
        raise NotImplemented

    def set(self, key: str, value: Any):
        self.changed = True
        self.state[key] = value

    def get(self, item: str, default=None):
        return self.state.get(item, default)

    def __getitem__(self, item: str):
        return self.get(item, None)

    def __setitem__(self, key: str, value: Any):
        self.set(key, value)


class ConfigmapState(State):
    def __init__(self, kubernetes_api_client, state: dict[str, Any]):
        self.api: kubernetes.client.CoreV1Api = kubernetes_api_client
        self.name = os.getenv("CONFIGMAP_NAME")
        self.namespace = os.getenv("CONFIGMAP_NAMESPACE")

        if not self.name or not self.namespace:
            raise ValueError("`CONFIGMAP_NAME` and `CONFIGMAP_NAMESPACE` have to be defined")
        self.configmap: Optional[V1ConfigMap] = None
        super().__init__(state)

    def initialize(self, bot):
        create = True
        for configmap in self.api.list_namespaced_config_map(self.namespace):
            if configmap.metadata.dictionary["name"] == self.name:
                create = False
                break

        if create:
            configmap = client.V1ConfigMap(
                api_version="v1",
                kind="ConfigMap",
                metadata=client.V1ObjectMeta(
                    name=self.name,
                    namespace=self.namespace,
                ),
                data=self.state
            )
            self.api.create_namespaced_config_map(self.namespace, configmap)
        super().initialize(bot)

    def read(self) -> dict[str, Any]:
        self.configmap = self.api.read_namespaced_config_map(self.name, self.namespace)
        if self.configmap.data is None:
            self.state = {}
        else:
            self.state = json.loads(base64.b64decode(self.configmap.data["state"]).decode("utf-8"))

        self.state["chats"] = {schat["id"]: Chat.deserialize(schat, self.bot) for schat in self.state.get("chats", [])}
        return self.state

    def write(self):
        if not self.changed:
            return

        state = self.state.copy()
        # noinspection PyTypeChecker
        state["chats"] = [chat.serialize() for chat in state["chats"].values()]
        value = json.dumps(state).encode("utf-8")
        value = base64.b64encode(value).decode("utf-8")
        self.configmap.data["state"] = value

        self.api.patch_namespaced_config_map(self.name, self.namespace, self.configmap)
        # otherwise we're getting a 409 from the k8s api due to the version difference
        self.read()
        self.changed = False


class FileState(State):
    def __init__(self, filepath: str, state: dict[str, Any]):
        super().__init__(state)
        self.filepath = filepath

    def read(self) -> dict[str, Any]:
        with open(self.filepath) as f:
            self.state = json.load(f)

        self.state["chats"] = {schat["id"]: Chat.deserialize(schat, self.bot) for schat in self.state.get("chats", [])}
        return self.state

    def write(self):
        if not self.changed:
            return

        with open(self.filepath, "w+") as f:
            json.dump(self.state, f)
        self.changed = False
