#!/bin/bash
set -e
source .env

echo "IP server: " $ORANGEPI_IP

scp ./* root@$ORANGEPI_IP:/srv/
ssh root@$ORANGEPI_IP "/srv/install.sh"
