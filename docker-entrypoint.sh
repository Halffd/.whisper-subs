#!/bin/bash

# Create user with same UID/GID as host user
if [ ! -z "$USERID" ] && [ ! -z "$GROUPID" ]; then
    groupadd -g $GROUPID appuser
    useradd -u $USERID -g $GROUPID -d /home/appuser -m appuser
    
    # Set password for SSH access
    echo "appuser:appuser" | chpasswd
    
    # Ensure Documents directory exists with correct permissions
    mkdir -p /home/appuser/Documents
    chown -R appuser:appuser /home/appuser
    
    # Setup SSH keys if needed
    if [ "$1" = "/usr/sbin/sshd" ]; then
        mkdir -p /home/appuser/.ssh
        ssh-keygen -A
        chown -R appuser:appuser /home/appuser/.ssh
        exec "$@"
    else
        # Run the application as the user
        exec gosu appuser "$@"
    fi
else
    # Fallback to root if no UID/GID specified
    exec "$@"
fi 