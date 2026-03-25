#!/bin/sh

echo "Waiting for Airflow API to be ready..."

until curl -s http://airflow-api:8080/health > /dev/null; do
  sleep 3
done

echo "API is ready. Creating admin user..."

curl -X POST "http://airflow-api:8080/api/v1/users" \
  -H "Content-Type: application/json" \
  -d "{
    \"username\": \"admin\",
    \"password\": \"admin\",
    \"email\": \"admin@example.com\",
    \"first_name\": \"Admin\",
    \"last_name\": \"User\",
    \"roles\": [\"Admin\"]
  }"

echo "Admin user created!"
