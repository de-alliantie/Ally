FROM python:3.10-slim-bookworm

COPY entrypoint_app.sh ./app/entrypoint.sh

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends dialog \
    && apt-get install -y --no-install-recommends openssh-server \
    && echo "root:Docker!" | chpasswd \
    && chmod u+x ./app/entrypoint.sh \
    && rm -rf /var/lib/apt/lists/*

ARG ENVIRONMENT="local"
ENV APP_ENVIRONMENT=$ENVIRONMENT
ARG BUILD_TAG=1
ENV APP_BUILD_TAG=$BUILD_TAG

WORKDIR /app
COPY requirements-webapp.txt requirements.txt 
RUN pip install --no-cache-dir -r requirements.txt

COPY .streamlit .streamlit
COPY sshd_config /etc/ssh/
COPY changelog.md ./
COPY src src

WORKDIR /app/src

RUN pip3 install -e .

WORKDIR ..

EXPOSE 8000 2222
HEALTHCHECK CMD curl --fail http://localhost:8000/_stcore/health

ENTRYPOINT ["./entrypoint.sh" ]