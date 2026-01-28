#!/bin/bash
#
# Generate self-signed certificates for HTTP/2 testing.
#
# Usage: ./generate_certs.sh
#

set -e

CERTS_DIR="./certs"
CERT_FILE="$CERTS_DIR/server.crt"
KEY_FILE="$CERTS_DIR/server.key"

# Create certs directory if it doesn't exist
mkdir -p "$CERTS_DIR"

# Check if certificates already exist
if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "Certificates already exist in $CERTS_DIR"
    echo "Delete them first if you want to regenerate."
    exit 0
fi

echo "Generating self-signed certificate..."

openssl req -x509 -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -days 365 \
    -nodes \
    -subj "/CN=localhost/O=Gunicorn HTTP2 Example/C=US" \
    -addext "subjectAltName=DNS:localhost,DNS:gunicorn,IP:127.0.0.1"

# Set appropriate permissions
chmod 644 "$CERT_FILE"
chmod 600 "$KEY_FILE"

echo "Certificates generated successfully:"
echo "  Certificate: $CERT_FILE"
echo "  Private Key: $KEY_FILE"
echo ""
echo "You can now start the server with:"
echo "  docker compose up -d"
echo ""
echo "Or run locally with:"
echo "  gunicorn --config gunicorn_conf.py app:app"
