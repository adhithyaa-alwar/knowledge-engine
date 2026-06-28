# Dockerfile
#
# This file tells Docker how to build your app into a container.
# Think of it as a recipe — Docker follows these steps top to bottom
# to create a standardized environment your app can run in.

# Step 1: Start from an official Python image.
# This is like choosing a base operating system that already has Python installed.
# "3.12-slim" is a lightweight version — just Python, nothing extra.
FROM python:3.12-slim

# Step 2: Set the working directory inside the container.
# All subsequent commands run from this folder.
WORKDIR /app

# Step 3: Copy requirements first (before the rest of the code).
# Docker caches each step — by copying requirements separately,
# it won't re-install packages every time you change your code.
COPY requirements.txt .

# Step 4: Install dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Step 5: Copy the rest of your project into the container.
COPY . .

# Step 6: Tell Docker your app listens on port 5000.
EXPOSE 5000

# Step 7: The command to run when the container starts.
CMD ["python", "app.py"]
