#!/bin/sh
set -e
service ssh start
exec streamlit run "./src/webapp/Chat met Ally.py" --server.port=8000