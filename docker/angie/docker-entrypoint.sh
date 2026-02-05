#!/bin/sh
set -e

# Process template files with envsubst
# Only substitute our variables, not nginx variables like $host, $request_uri
for template in /etc/angie/templates/*.template; do
    if [ -f "$template" ]; then
        output="/etc/angie/$(basename "$template" .template)"
        envsubst '${DOMAIN}' < "$template" > "$output"
    fi
done

exec "$@"
