```
delete_chat - Deletes all data associated with this chat (admin command)
status - Returns the chat id ([{id}])
version - Returns the SHA1 of the current commit
server_time - Time on the server (debugging purposes)
users - Shows every user in the chat who has participated in the chat at some time (format: `str(user} ({attendance_count}/{#chat.events})`)
get_data - Returns the state representation for the current chat as a file ({chat.title}.json)
mute - (<user.first_name> [<timeout in minutes>] [<reason>]) Mutes the `user` for the given timeframe (15 minutes if none is given) (admin command)
unmute - (<user.first_name>) Unmutes the provided `user` (admin command)
kick - (<user.first_name> [<reason>]) kicks a user from the chat
add_invite_link - (<invite_link>) Adds an invite link to the group which other users can retrieve
remove_invite_link - Removes the saved invite link (does nothing when not present)
get_invite_link - (<group_name>) gets the invite link for the given group (when an invite link is present)
renew_diff_message - Sends the diff message to the group again (does not delete the old one)
```
