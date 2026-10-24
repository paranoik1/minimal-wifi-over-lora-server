#!/bin/bash
# Установка обновлений, poetry и зависимостей к проекту
set -e


apt update -y && apt upgrade -y
apt install pipx

pipx install poetry

cd /srv
poetry install
