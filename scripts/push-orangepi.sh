#!/bin/bash
set -e
source .env

echo "IP server: "$ORANGEPI_IP


# FIXME: ориентироваться лишь на git изменения плохо, так как позже надо будет деплоить проект
# без каких либо изменений в git на orangepi
# changed_files=$(git status -s | awk '{ print $2 }') 

# if [[ "G"$changed_files != "G" ]]; then
#     scp -r ./* root@$ORANGEPI_IP:/srv/
# else
#     echo "Нет изменений в git"
# fi
scp -r ./* root@$ORANGEPI_IP:/srv/

# ssh root@$ORANGEPI_IP "/srv/install.sh"
