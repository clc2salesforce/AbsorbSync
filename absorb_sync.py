#!/usr/bin/env python3
"""
Absorb LMS External ID Sync Script

This script downloads values from a source field (default: 'externalId') from Absorb LMS user accounts
and uploads it back to a specified custom field. By default, it targets the 'Associate Number' field (customFields.decimal1), 
but can be configured to sync to any custom field using the --customField flag (e.g., decimal1, string1, string2, etc.).
The source field can also be customized using the --sourceField flag.

Features:
- Exponential backoff retry logic
- Text file logging
- Dry run mode
- Secrets loaded from external file
- Configurable source and target custom fields
"""

import argparse
import csv
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

try:
    import requests
except ImportError:
    print("Error: 'requests' module not found. Install it with: pip install -r requirements.txt")
    sys.exit(1)


class AbsorbLMSClient:
    """Client for interacting with Absorb LMS API."""
    
    def __init__(self, api_url: str, api_key: str, username: str, password: str, debug: bool = False):
        """
        Initialize the Absorb LMS client.
        
        Args:
            api_url: Base URL for the Absorb LMS API
            api_key: API key for x-api-key header and privateKey in authentication
            username: API username for authentication
            password: API password for authentication
            debug: Enable debug logging (prints API key in cleartext)
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.username = username
        self.password = password
        self.debug = debug
        self.session = requests.Session()
        # Set the API key header for all requests
        self.session.headers.update({
            "x-api-key": self.api_key
        })
        self.token = None
        
        if self.debug:
            logging.info("="*60)
            logging.info("DEBUG MODE ENABLED - Sensitive data will be logged")
            logging.info("="*60)
            logging.info(f"DEBUG: API URL: {self.api_url}")
            logging.info(f"DEBUG: API Key: {self.api_key}")
            logging.info(f"DEBUG: Username: {self.username}")
            logging.info(f"DEBUG: Password: {self.password}")
            logging.info("="*60)
        
    def authenticate(self) -> bool:
        """
        Authenticate with the Absorb LMS REST API v2.
        
        Uses the /authenticate endpoint which requires:
        - x-api-key header (already set)
        - POST body with username, password, and privateKey (same as api_key)
        
        Returns an authentication token that must be used in subsequent API calls.
        
        Returns:
            bool: True if authentication successful, False otherwise
        """
        # Authenticate using the /authenticate endpoint
        auth_url = f"{self.api_url}/authenticate"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # Request body - privateKey is the same as the API key
        data = {
            "username": self.username,
            "password": self.password,
            "privateKey": self.api_key
        }
        
        try:
            logging.info("Authenticating with Absorb LMS REST API v2...")
            response = self._retry_request(
                method='POST',
                url=auth_url,
                headers=headers,
                json=data
            )
            
            if response.status_code == 200:
                # The response is the authentication token as a string
                self.token = response.text.strip('"')  # Remove quotes if present
                if self.token:
                    # Set the token for subsequent requests (no "Bearer " prefix)
                    self.session.headers.update({
                        "Authorization": self.token
                    })
                    logging.info("Authentication successful")
                    return True
                else:
                    logging.error("Empty token received from authentication endpoint")
                    return False
            else:
                logging.error(f"Authentication failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"Authentication error: {str(e)}")
            return False
    
    def _retry_request(self, method: str, url: str, max_retries: int = 5, 
                      initial_delay: float = 1.0, max_reauth_attempts: int = 1, **kwargs) -> requests.Response:
        """
        Make an HTTP request with exponential backoff retry logic and automatic reauthentication.
        
        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            url: URL to request
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay in seconds before first retry
            max_reauth_attempts: Maximum number of reauthentication attempts on 401 errors (default: 1)
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            requests.Response: The response object if successful
            
        Raises:
            Exception: If all retries are exhausted, an exception is always raised
                      rather than returning a response
        """
        delay = initial_delay
        last_error = None
        reauth_attempts = 0
        
        # Debug logging for the request
        if self.debug:
            logging.info("="*60)
            logging.info(f"DEBUG: HTTP Request Details")
            logging.info(f"DEBUG: Method: {method}")
            logging.info(f"DEBUG: URL: {url}")
            
            # Log headers (merge session headers with request-specific headers)
            headers = dict(self.session.headers)
            if 'headers' in kwargs:
                headers.update(kwargs['headers'])
            logging.info(f"DEBUG: Headers: {headers}")
            
            # Log request body if present
            if 'json' in kwargs:
                logging.info(f"DEBUG: JSON Body: {kwargs['json']}")
            elif 'data' in kwargs:
                logging.info(f"DEBUG: Data Body: {kwargs['data']}")
            
            # Log params if present
            if 'params' in kwargs:
                logging.info(f"DEBUG: Params: {kwargs['params']}")
            logging.info("="*60)
        
        attempt = 0
        while True:
            try:
                response = self.session.request(method, url, **kwargs)
                
                # Debug logging for the response
                if self.debug:
                    logging.info("="*60)
                    logging.info(f"DEBUG: HTTP Response")
                    logging.info(f"DEBUG: Status Code: {response.status_code}")
                    logging.info(f"DEBUG: Response Headers: {dict(response.headers)}")
                    logging.info(f"DEBUG: Response Body: {response.text[:500]}...")  # First 500 chars
                    logging.info("="*60)
                
                # Handle 401 Unauthorized - token may have expired
                if response.status_code == 401:
                    # Check if this is the authenticate endpoint by comparing with the auth URL
                    auth_url = f"{self.api_url}/authenticate"
                    is_auth_endpoint = url.rstrip('/') == auth_url.rstrip('/')
                    
                    # Skip reauthentication if this is the authenticate endpoint itself
                    if not is_auth_endpoint and reauth_attempts < max_reauth_attempts:
                        reauth_attempts += 1
                        logging.warning(
                            f"Received 401 Unauthorized. Attempting reauthentication "
                            f"({reauth_attempts}/{max_reauth_attempts})..."
                        )
                        if self.authenticate():
                            logging.info("Reauthentication successful. Retrying original request...")
                            # Continue without incrementing attempt counter
                            continue
                        else:
                            logging.error("Reauthentication failed")
                            return response
                    else:
                        # Either this is the auth endpoint, or we've exhausted reauth attempts
                        return response
                
                # If we get a rate limit or server error, retry
                if response.status_code in [429, 500, 502, 503, 504]:
                    if attempt < max_retries - 1:
                        attempt += 1
                        logging.warning(
                            f"Retry {attempt}/{max_retries} for {method} {url} "
                            f"(status: {response.status_code})"
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                        continue
                    else:
                        # Last attempt failed with retryable status code
                        raise Exception(
                            f"Max retries exceeded. Last status: {response.status_code}"
                        )
                
                # For successful or non-retryable responses, return immediately
                return response
                
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                if self.debug:
                    logging.info(f"DEBUG: Request Exception: {last_error}")
                if attempt < max_retries - 1:
                    attempt += 1
                    logging.warning(
                        f"Retry {attempt}/{max_retries} for {method} {url} "
                        f"(error: {last_error})"
                    )
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    raise Exception(f"Max retries exceeded: {last_error}")
            
    def get_users_incremental(self, page_size: int = 500, csv_file: str = None, filter_blank: bool = False, department_id: str = None, destination_field: str = 'customFields.decimal1', source_field: str = 'externalId') -> int:
        """
        Retrieve all users from Absorb LMS with pagination and save to CSV incrementally.
        
        Args:
            page_size: Number of users to retrieve per page (default: 500)
            csv_file: Path to CSV file to save users incrementally
            filter_blank: If True, only retrieve users where the destination field is null
            department_id: If provided, filter by departmentId
            destination_field: Full path to destination field to sync (default: customFields.decimal1)
            source_field: Name of the source field to sync from (default: externalId)
            
        Returns:
            Total number of users with the source field retrieved
        """
        page = 0  # Page number (0-indexed)
        total_items = None
        total_pages = None
        users_with_source_field = 0
        
        # Extract column name for CSV
        dest_col_name = f'current_{sanitize_field_path_for_csv(destination_field)}'
        
        # Open CSV file and write header
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Status', 'id', 'username', source_field, dest_col_name, 'user_data_json'])
            
            while True:
                url = f"{self.api_url}/users"
                params = {
                    "_limit": page_size,
                    "_offset": page  # Page number, not offset by page_size
                }
                
                # Build OData filter
                filters = []
                if filter_blank:
                    # For customFields, use the format customFields/{fieldname}
                    if destination_field.startswith('customFields.'):
                        field_name = destination_field.split('.', 1)[1]
                        filters.append(f"customFields/{field_name} eq null")
                    else:
                        filters.append(f"{destination_field} eq null")
                if department_id:
                    filters.append(f"departmentId eq guid'{department_id}'")
                
                # Combine filters with 'and' if multiple
                if filters:
                    params["_filter"] = " and ".join(filters)
                
                try:
                    response = self._retry_request('GET', url, params=params)
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        # Get total items from first response to calculate pages
                        if total_items is None:
                            total_items = data.get('totalItems', 0)
                            total_pages = (total_items + page_size - 1) // page_size  # Ceiling division
                            logging.info(f"Total users to retrieve: {total_items}")
                            logging.info(f"Will download in {total_pages} batches of {page_size}")
                        
                        # The API returns 'users' (lowercase)
                        page_users = data.get('users', [])
                        
                        if not page_users:
                            break
                        
                        # Write users to CSV immediately after retrieving each batch
                        batch_count = 0
                        for user in page_users:
                            user_id = user.get('id', '')
                            username = user.get('username', 'Unknown')
                            source_value = get_nested_field_value(user, source_field)
                            
                            # Skip users without source field value
                            if not source_value:
                                continue
                            
                            # Get current destination field value
                            current_dest_value = get_nested_field_value(user, destination_field)
                            
                            # Store entire user data as JSON for PUT later
                            user_data_json = json.dumps(user)
                            
                            writer.writerow(['Retrieved', user_id, username, source_value, current_dest_value, user_data_json])
                            batch_count += 1
                            users_with_source_field += 1
                        
                        # Flush to ensure data is written to disk after each batch
                        f.flush()
                        
                        current_batch = page + 1
                        logging.info(f"Downloading user batch {current_batch} of {total_pages} ({len(page_users)} users, {batch_count} with {source_field})")
                        
                        page += 1  # Increment page number by 1
                        
                        # Check if we've retrieved all users based on returned count
                        if len(page_users) < page_size:
                            break
                    else:
                        error_msg = f"Failed to retrieve users: {response.status_code} - {response.text}"
                        logging.error(error_msg)
                        raise RuntimeError(error_msg)
                        
                except Exception as e:
                    logging.error(f"Error retrieving users: {str(e)}")
                    raise
        
        logging.info(f"Total users with {source_field} saved to CSV: {users_with_source_field}")
        return users_with_source_field
    
    def update_user(self, user_data: Dict[str, Any], source_value: str, destination_field: str) -> bool:
        """
        Update a user's destination field with the source field value.
        
        Args:
            user_data: Complete user data dictionary
            source_value: Source field value to set in the destination field
            destination_field: Full path to the destination field (e.g., 'customFields.decimal1', 'externalId')
            
        Returns:
            bool: True if update successful, False otherwise
        """
        user_id = user_data.get('id')
        url = f"{self.api_url}/users/{user_id}"
        
        try:
            # Determine the appropriate value type based on the destination field name
            # If it's a decimal field, convert to float
            field_name = destination_field.split('.')[-1] if '.' in destination_field else destination_field
            if field_name.startswith('decimal'):
                try:
                    field_value = float(source_value)
                except (ValueError, TypeError):
                    logging.warning(f"Cannot convert source value '{source_value}' to decimal for user {user_id}")
                    return False
            else:
                # For string fields and others, use the value as-is
                field_value = source_value
            
            # Set the destination field value using the helper function
            set_nested_field_value(user_data, destination_field, field_value)
            
            # PUT the entire user profile back
            headers = {
                "Content-Type": "application/json"
            }
            response = self._retry_request(
                'PUT',
                url,
                headers=headers,
                json=user_data
            )
            
            if response.status_code in [200, 201, 204]:
                return True
            else:
                logging.error(
                    f"Failed to update user {user_id}: {response.status_code} - {response.text}"
                )
                return False
                
        except Exception as e:
            logging.error(f"Error updating user {user_id}: {str(e)}")
            return False


def get_nested_field_value(data: Dict[str, Any], field_path: str) -> str:
    """
    Extract a field value from a nested dictionary using dot notation.
    
    Args:
        data: Dictionary containing user data
        field_path: Field path using dot notation (e.g., 'externalId', 'customFields.string1')
        
    Returns:
        Field value as string, or empty string if not found
    """
    if '.' in field_path:
        # Handle nested fields
        parts = field_path.split('.')
        value = data
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
                if value is None:
                    return ''
            else:
                return ''
        return str(value) if value is not None else ''
    else:
        # Simple field
        value = data.get(field_path, '')
        return str(value) if value else ''


def set_nested_field_value(data: Dict[str, Any], field_path: str, value: Any) -> None:
    """
    Set a field value in a nested dictionary using dot notation.
    
    Args:
        data: Dictionary containing user data
        field_path: Field path using dot notation (e.g., 'externalId', 'customFields.string1')
        value: Value to set
    """
    if '.' in field_path:
        # Handle nested fields
        parts = field_path.split('.')
        current = data
        
        # Navigate to the parent of the target field, creating dicts as needed
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        
        # Set the final value
        current[parts[-1]] = value
    else:
        # Simple field
        data[field_path] = value


def sanitize_field_path_for_csv(field_path: str) -> str:
    """
    Sanitize a field path for use as a CSV column name by replacing dots with underscores.
    
    Args:
        field_path: Field path (e.g., 'customFields.decimal1')
        
    Returns:
        Sanitized field path (e.g., 'customFields_decimal1')
    """
    return field_path.replace('.', '_')


def load_secrets(secrets_file: str = 'secrets.txt') -> Dict[str, str]:
    """
    Load secrets from a text file.
    
    Args:
        secrets_file: Path to the secrets file
        
    Returns:
        Dictionary of configuration values
        
    Raises:
        FileNotFoundError: If secrets file doesn't exist
        ValueError: If required secrets are missing
    """
    if not os.path.exists(secrets_file):
        raise FileNotFoundError(
            f"Secrets file '{secrets_file}' not found. "
            f"Copy 'secrets.txt.example' to '{secrets_file}' and fill in your credentials."
        )
    
    secrets = {}
    with open(secrets_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            if '=' in line:
                key, value = line.split('=', 1)
                secrets[key.strip()] = value.strip()
    
    # Validate required secrets
    required_keys = [
        'ABSORB_API_URL',
        'ABSORB_API_KEY',
        'ABSORB_API_USERNAME',
        'ABSORB_API_PASSWORD'
    ]
    
    missing_keys = [key for key in required_keys if key not in secrets]
    if missing_keys:
        raise ValueError(f"Missing required secrets: {', '.join(missing_keys)}")
    
    return secrets


def setup_logging(log_file: str = None) -> None:
    """
    Set up logging configuration.
    
    Args:
        log_file: Path to log file (optional)
    """
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        # Create logs directory if it doesn't exist
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=handlers
    )


def parse_int_from_string(value: str) -> Optional[int]:
    """
    Parse an integer from a string, handling floats by converting to int.
    
    Args:
        value: String value to parse
        
    Returns:
        Integer value or None if parsing fails
    """
    if not value:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def is_numeric_only(value: str) -> bool:
    """
    Check if a string contains only numeric characters (digits).
    
    Args:
        value: String to check
        
    Returns:
        True if string contains only digits, False otherwise
    """
    if not value:
        return False
    return value.isdigit()


def sync_external_ids(client: AbsorbLMSClient, dry_run: bool = False, csv_file: str = None, 
                      filter_blank: bool = False, overwrite: bool = False, 
                      use_existing_file: bool = False, allow_alpha: bool = False,
                      department_id: str = None, destination_field: str = 'customFields.decimal1', source_field: str = 'externalId') -> tuple:
    """
    Sync values from the source field to the specified destination field.
    
    Args:
        client: Authenticated AbsorbLMSClient instance
        dry_run: If True, only simulate the sync without making changes
        csv_file: Path to CSV file for storing user data
        filter_blank: If True, only process users with null destination field value
        overwrite: If True, update even if destination field already has a value
        use_existing_file: If True, skip download and use existing CSV file
        allow_alpha: If True, allow alphanumeric source values; otherwise only numeric
        department_id: If provided, filter by departmentId
        destination_field: Full path to destination field (default: customFields.decimal1)
        source_field: Name of the source field to sync from (default: externalId)
        
    Returns:
        Tuple of (success_count, error_count, skip_count)
    """
    if csv_file is None:
        csv_file = f'users_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    logging.info("Starting field sync...")
    logging.info(f"Source field: {source_field}")
    logging.info(f"Destination field: {destination_field}")
    
    if dry_run:
        logging.info("DRY RUN MODE - No changes will be made")
    
    if filter_blank:
        logging.info(f"Filtering for users with null/empty {destination_field} field only")
    
    if department_id:
        logging.info(f"Filtering for users in department: {department_id}")
    
    if not allow_alpha:
        logging.info(f"Validating {source_field} values are numeric only (use --alpha to allow alphanumeric)")
    
    if not overwrite:
        logging.info(f"Will skip users where {source_field} doesn't match existing {destination_field} value (marked as 'Different')")
    
    # Get all users and save incrementally to CSV, or use existing file
    if use_existing_file:
        if not os.path.exists(csv_file):
            raise FileNotFoundError(f"CSV file not found: {csv_file}")
        logging.info(f"Using existing CSV file: {csv_file}")
        
        # Count users in CSV
        with open(csv_file, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            users_count = sum(1 for _ in reader)
        
        logging.info(f"Found {users_count} users in CSV file")
    else:
        logging.info("Fetching users from Absorb LMS...")
        users_count = client.get_users_incremental(page_size=500, csv_file=csv_file, filter_blank=filter_blank, department_id=department_id, destination_field=destination_field, source_field=source_field)
    
    if users_count == 0:
        logging.warning(f"No users with {source_field} found. Exiting.")
        return 0, 0, 0
    
    # Ask for confirmation
    logging.info("\n" + "="*60)
    logging.info(f"Ready to process {users_count} users")
    logging.info("="*60)
    
    if not dry_run:
        try:
            confirmation = input(f"\nDo you want to proceed with updating {users_count} users? (yes/y/no): ")
            if confirmation.lower() not in ['yes', 'y']:
                logging.info("Update cancelled by user")
                return 0, 0, 0
        except (EOFError, KeyboardInterrupt):
            logging.info("\nUpdate cancelled by user")
            return 0, 0, 0
    
    # Process the CSV file and update incrementally
    logging.info("\nProcessing users...")
    success_count = 0
    error_count = 0
    skip_count = 0  # Initialize as local variable
    
    # Helper function to skip a user and write to CSV
    def skip_user(row, status, message, writer, f_out):
        """Skip a user, update status, log, and write to CSV."""
        nonlocal skip_count
        logging.info(message)
        row['Status'] = status
        skip_count += 1
        writer.writerow(row)
        f_out.flush()
    
    # Read CSV, process each user, and update CSV incrementally
    temp_csv = None
    temp_dir = os.path.dirname(csv_file) or '.'
    with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=temp_dir, suffix='.tmp', newline='', encoding='utf-8') as temp_file:
        temp_csv = temp_file.name
    
    try:
        # Move original CSV to temp for reading; write updates directly to original.
        # This ensures the status column in the CSV is updated after each API call,
        # not once after all updates complete.
        if not dry_run:
            os.replace(csv_file, temp_csv)
        
        read_path = temp_csv if not dry_run else csv_file
        write_path = csv_file if not dry_run else temp_csv
        
        with open(read_path, 'r', newline='', encoding='utf-8') as f_in, \
             open(write_path, 'w', newline='', encoding='utf-8') as f_out:
            
            reader = csv.DictReader(f_in)
            fieldnames = reader.fieldnames
            writer = csv.DictWriter(f_out, fieldnames=fieldnames)
            writer.writeheader()
            
            # Get the destination field column name from CSV
            dest_col_name = f'current_{sanitize_field_path_for_csv(destination_field)}'
            
            for row in reader:
                user_id = row['id']
                username = row['username']
                source_value = row[source_field]
                # Get current destination field value using dynamic column name
                current_field_value = row.get(dest_col_name, '')
                user_data_json = row['user_data_json']
                
                try:
                    user_data = json.loads(user_data_json)
                except json.JSONDecodeError as e:
                    logging.error(f"Failed to parse user data for {username}: {e}")
                    row['Status'] = 'Failure'
                    error_count += 1
                    writer.writerow(row)
                    f_out.flush()  # Flush after each row
                    continue
                
                # Check if source value is blank but destination field is set
                if not source_value and current_field_value:
                    skip_user(row, 'Different', 
                             f"Skipping user {username} (ID: {user_id}) - {source_field} is blank but {destination_field} is set: {current_field_value}",
                             writer, f_out)
                    continue
                
                # Skip users with blank source value (and blank destination field, since we already handled blank source + set destination field)
                if not source_value:
                    continue
                
                # Validate source value format if not allowing alphanumeric
                if not allow_alpha and not is_numeric_only(source_value):
                    skip_user(row, 'Wrong Format',
                             f"Skipping user {username} (ID: {user_id}) - {source_field} '{source_value}' is not numeric (use --alpha to allow alphanumeric)",
                             writer, f_out)
                    continue
                
                # Check if we should skip this user based on overwrite flag
                # For decimal fields, remove decimals for comparison (source value may be a whole number)
                # For string fields, compare directly
                current_field_int = parse_int_from_string(current_field_value)
                source_value_int = parse_int_from_string(source_value)
                
                # Skip if values don't match and overwrite is False
                if not overwrite and current_field_int is not None and current_field_int != source_value_int:
                    skip_user(row, 'Different',
                             f"Skipping user {username} (ID: {user_id}) - {source_field}: {source_value}, Current {destination_field}: {current_field_value} (different values)",
                             writer, f_out)
                    continue
                
                logging.info(f"Processing user {username} (ID: {user_id}) - {source_field}: {source_value}")
                
                if dry_run:
                    logging.info(f"[DRY RUN] Would update {destination_field} to: {source_value}")
                    row['Status'] = 'Success'
                    success_count += 1
                else:
                    if client.update_user(user_data, source_value, destination_field):
                        logging.info(f"Successfully updated user {username}")
                        row['Status'] = 'Success'
                        success_count += 1
                    else:
                        logging.error(f"Failed to update user {username}")
                        row['Status'] = 'Failure'
                        error_count += 1
                
                writer.writerow(row)
                f_out.flush()  # Flush after each row to ensure it's written to disk
        
        # Files are now closed, safe to clean up
        # In non-dry-run mode, updates were written directly to csv_file
        # In dry-run mode, updates were written to temp_csv (original unchanged)
        if os.path.exists(temp_csv):
            os.remove(temp_csv)
        if not dry_run:
            logging.info(f"Updated CSV saved to {csv_file}")
    
    except Exception as e:
        logging.error(f"Error during processing: {e}")
        if not dry_run and temp_csv and os.path.exists(temp_csv):
            # In non-dry-run mode, temp file contains original data as backup
            logging.warning(f"Original data preserved in temporary file: {temp_csv}")
        elif temp_csv and os.path.exists(temp_csv):
            try:
                os.remove(temp_csv)
            except OSError as cleanup_error:
                logging.warning(f"Could not remove temporary file {temp_csv}: {cleanup_error}")
        raise
    
    logging.info(f"\n{'='*60}")
    logging.info(f"Sync completed!")
    logging.info(f"Total users processed: {success_count + error_count + skip_count}")
    logging.info(f"Successful updates: {success_count}")
    logging.info(f"Skipped (different values): {skip_count}")
    logging.info(f"Errors: {error_count}")
    logging.info(f"{'='*60}\n")
    
    return success_count, error_count, skip_count


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Absorb LMS Field Sync - Synchronize values from a source field to a destination field',
        epilog='''
Examples:
  # Dry-run mode (default - preview changes without modifying data)
  python absorb_sync.py --customField decimal1
  
  # Actually perform updates (requires --update flag)
  python absorb_sync.py --customField decimal1 --update
  
  # Sync to a different custom field (e.g., string1) using --customField
  python absorb_sync.py --customField string1 --update
  
  # Sync from a different source field (e.g., username)
  python absorb_sync.py --sourceField username --customField string1 --update
  
  # Sync from a custom field to another custom field
  python absorb_sync.py --sourceField customFields.string2 --customField decimal1 --update
  
  # Sync to any destination field using --destinationField
  python absorb_sync.py --sourceField customFields.string1 --destinationField externalId --update
  
  # Sync from username to externalId
  python absorb_sync.py --sourceField username --destinationField externalId --update
  
  # Filter by department
  python absorb_sync.py --customField decimal1 --department c458459d-2f86-4c66-a481-e17e6983f7ee --update
  
  # Only update users with blank destination field
  python absorb_sync.py --customField decimal1 --blank --update
  
  # Update all users, even if destination field already has a different value
  python absorb_sync.py --customField decimal1 --overwrite --update
  
  # Allow alphanumeric source values (default: numeric only)
  python absorb_sync.py --customField decimal1 --alpha --update
  
  # Process existing CSV file instead of downloading
  python absorb_sync.py --customField decimal1 --file users_20260219_123456.csv --update
  
  # Combine multiple options
  python absorb_sync.py --sourceField externalId --customField decimal2 --blank --department <dept-id> --alpha --update
  
  # Debug mode (prints sensitive data including API keys)
  python absorb_sync.py --debug --dry-run

For more information, see README.md or visit https://github.com/clc2salesforce/AbsorbSync
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Configuration options
    config_group = parser.add_argument_group('Configuration Options')
    config_group.add_argument(
        '--secrets',
        default='secrets.txt',
        metavar='FILE',
        help='Path to secrets file containing API credentials (default: secrets.txt)'
    )
    config_group.add_argument(
        '--log-file',
        default=None,
        metavar='FILE',
        help='Path to log file (default: logs/absorb_sync_YYYYMMDD_HHMMSS.log)'
    )
    config_group.add_argument(
        '--csv-file',
        default=None,
        metavar='FILE',
        help='Path to CSV file for storing user data (default: users_YYYYMMDD_HHMMSS.csv)'
    )
    
    # Processing mode options
    mode_group = parser.add_argument_group('Processing Mode Options')
    mode_group.add_argument(
        '--update',
        action='store_true',
        help='Actually perform updates to Absorb LMS (default is dry-run mode)'
    )
    mode_group.add_argument(
        '--dry-run',
        action='store_true',
        help='Explicitly enable dry-run mode (no changes will be made). This is the default behavior.'
    )
    mode_group.add_argument(
        '--file',
        default=None,
        metavar='FILE',
        help='Process existing CSV file instead of downloading from API (skips download phase)'
    )
    
    # Filtering options
    filter_group = parser.add_argument_group('Filtering Options')
    filter_group.add_argument(
        '--blank',
        action='store_true',
        help='Filter to only users with null/empty custom field (uses OData filter)'
    )
    filter_group.add_argument(
        '--department',
        default=None,
        metavar='DEPT_ID',
        help='Filter by departmentId UUID (e.g., c458459d-2f86-4c66-a481-e17e6983f7ee)'
    )
    
    # Validation and behavior options
    behavior_group = parser.add_argument_group('Validation and Behavior Options')
    behavior_group.add_argument(
        '--overwrite',
        action='store_true',
        help='Update custom field even if it already has a different value (default: skip and mark as "Different")'
    )
    behavior_group.add_argument(
        '--alpha',
        action='store_true',
        help='Allow alphanumeric externalIds (default: numeric only, non-numeric marked as "Wrong Format")'
    )
    behavior_group.add_argument(
        '--customField',
        default=None,
        metavar='FIELD',
        help='Custom field to sync to (e.g., decimal1, decimal2, string1, string2). '
             'Only specify the field name under customFields. Decimal fields will be converted to float, '
             'string fields will remain as strings. Verify the field exists in your Absorb LMS instance. '
             'Cannot be used with --destinationField. Either --customField or --destinationField is required.'
    )
    behavior_group.add_argument(
        '--destinationField',
        default=None,
        metavar='FIELD',
        help='Destination field to sync to (e.g., externalId, username, customFields.string1). '
             'Use full field path with dot notation for nested fields. '
             'Cannot be used with --customField. Either --customField or --destinationField is required.'
    )
    behavior_group.add_argument(
        '--sourceField',
        default='externalId',
        metavar='FIELD',
        help='Source field to sync from (default: externalId). Can be any field from the user object '
             '(e.g., externalId, username, emailAddress) or a nested field like customFields.string1. '
             'For custom fields, specify the full path (e.g., customFields.decimal1).'
    )
    
    # Debug options
    debug_group = parser.add_argument_group('Debug Options')
    debug_group.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode (prints sensitive data including API keys and credentials - USE ONLY IN SANDBOX)'
    )
    
    args = parser.parse_args()
    
    # Validate that either --customField or --destinationField is provided, but not both
    if args.customField and args.destinationField:
        parser.error("Cannot use both --customField and --destinationField. Please specify only one.")
    
    # Require that one of the destination flags is specified
    if not args.customField and not args.destinationField:
        parser.error("Either --customField or --destinationField must be specified.")
    
    # Convert customField to full destination path for consistency
    if args.customField:
        args.destinationField = f'customFields.{args.customField}'
    
    # Handle dry-run vs update flag precedence
    # If --update is specified, disable dry-run (unless --dry-run is also explicitly set)
    if args.update and not args.dry_run:
        args.dry_run = False  # Enable updates
    else:
        # Default to dry-run mode if --update is not specified, or if --dry-run is explicitly set
        args.dry_run = True
    
    # Generate default log file name at runtime if not specified
    if args.log_file is None:
        args.log_file = f'logs/absorb_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    
    # Set up logging
    setup_logging(args.log_file)
    
    logging.info("="*60)
    logging.info("Absorb LMS Field Sync")
    logging.info("="*60)
    
    try:
        # Determine CSV file path
        csv_file_path = args.file if args.file else args.csv_file
        use_existing_file = args.file is not None
        
        # Load secrets and authenticate
        # Authentication is needed for both download and update operations
        # (even with --file, updates require API calls)
        logging.info(f"Loading secrets from {args.secrets}...")
        secrets = load_secrets(args.secrets)
        
        # Initialize client
        logging.info("Initializing Absorb LMS client...")
        client = AbsorbLMSClient(
            api_url=secrets['ABSORB_API_URL'],
            api_key=secrets['ABSORB_API_KEY'],
            username=secrets['ABSORB_API_USERNAME'],
            password=secrets['ABSORB_API_PASSWORD'],
            debug=args.debug
        )
        
        # Authenticate
        logging.info("Authenticating with Absorb LMS...")
        if not client.authenticate():
            logging.error("Authentication failed. Exiting.")
            sys.exit(1)
        
        if use_existing_file:
            logging.info(f"Using existing CSV file: {csv_file_path}")
        
        # Sync fields
        success_count, error_count, skip_count = sync_external_ids(
            client, 
            dry_run=args.dry_run,
            csv_file=csv_file_path,
            filter_blank=args.blank,
            overwrite=args.overwrite,
            use_existing_file=use_existing_file,
            allow_alpha=args.alpha,
            department_id=args.department,
            destination_field=args.destinationField,
            source_field=args.sourceField
        )
        
        # Exit with appropriate code
        if error_count > 0:
            logging.warning(f"Completed with {error_count} errors")
            sys.exit(1)
        else:
            logging.info("Completed successfully")
            sys.exit(0)
            
    except FileNotFoundError as e:
        logging.error(str(e))
        sys.exit(1)
    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
