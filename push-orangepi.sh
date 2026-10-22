#!/bin/bash
set -e
source .env

echo "IP server: " $ORANGEPI_IP


changed_files=$(git status -s | awk '{ print $2 }') 

scp ./* root@$ORANGEPI_IP:/srv/
ssh root@$ORANGEPI_IP "/srv/install.sh"
