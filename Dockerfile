FROM python:3.12.3-bookworm

ARG ARCH=amd64
ARG VERSION=v1.14.0

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt && \
    wget -q https://github.com/vmware-tanzu/velero/releases/download/${VERSION}/velero-${VERSION}-linux-${ARCH}.tar.gz && \
    tar -xf velero-${VERSION}-linux-${ARCH}.tar.gz && \
    mv velero-${VERSION}-linux-${ARCH}/velero /usr/local/bin/velero && \
    chmod +  /usr/local/bin/velero && \
    rm -rf velero-${VERSION}-*
RUN chown -R nobody:nogroup /app
USER nobody
ENTRYPOINT ["python", "velero-watchdog.py"]
