#!/bin/bash

# Create user with same UID/GID as host user
if [ ! -z "$HOST_UID" ] && [ ! -z "$HOST_GID" ]; then
    groupadd -g $HOST_GID appuser
    useradd -u $HOST_UID -g $HOST_GID -d /home/appuser -m appuser
    
    # Ensure Documents directory exists with correct permissions
    mkdir -p /home/appuser/Documents
    chown -R appuser:appuser /home/appuser/Documents
    
    # Run the application as the user
    exec gosu appuser python3 youtubesubs.py "$@"
else
    # Fallback to root if no UID/GID specified
    exec python3 youtubesubs.py "$@"
fi 