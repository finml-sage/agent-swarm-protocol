#!/bin/bash
# Generate self-signed certificates for development
# Usage: ./generate-dev-certs.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="${SCRIPT_DIR}/dev"

mkdir -p "${CERT_DIR}"

echo "Generating self-signed certificate for localhost..."

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "${CERT_DIR}/privkey.pem" \
    -out "${CERT_DIR}/fullchain.pem" \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

chmod 600 "${CERT_DIR}/privkey.pem"
chmod 644 "${CERT_DIR}/fullchain.pem"

echo "Development certificates generated in ${CERT_DIR}/"
echo "  - fullchain.pem (certificate)"
echo "  - privkey.pem (private key)"
