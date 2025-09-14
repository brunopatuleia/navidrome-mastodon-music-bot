# Use an official lightweight Python image as a base
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the script and its dependencies into the container
COPY main.py .
COPY secrets.py .

# Install the only Python library we need: 'requests'
RUN pip install requests

# Command to run when the container starts
CMD ["python", "main.py"]
