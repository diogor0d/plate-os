FROM postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73

ARG TARGETARCH
ARG AGE_VERSION=1.3.1

RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) AGE_SHA256="bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377" ;; \
      arm64) AGE_SHA256="c6878a324421b69e3e20b00ba17c04bc5c6dab0030cfe55bf8f68fa8d9e9093a" ;; \
      *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    wget -q -O /tmp/age.tar.gz \
      "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-${TARGETARCH}.tar.gz"; \
    echo "${AGE_SHA256}  /tmp/age.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/age.tar.gz -C /tmp; \
    cp /tmp/age/age /usr/local/bin/age; \
    cp /tmp/age/age-keygen /usr/local/bin/age-keygen; \
    chmod 0755 /usr/local/bin/age /usr/local/bin/age-keygen; \
    rm -rf /tmp/age /tmp/age.tar.gz

COPY --chmod=0755 backup.sh /usr/local/bin/backup
COPY --chmod=0755 restore.sh /usr/local/bin/restore

ENV HOME=/tmp
ENTRYPOINT []
CMD ["backup"]
