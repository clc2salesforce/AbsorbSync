#!/usr/bin/env python3
"""
Absorb LMS External ID Sync Script

This script downloads the 'external ID' field from Absorb LMS user accounts
and uploads it back to the same users' 'Associate Number' field. Note: the 'Associate Number' field is a custom field that is referenced based on the order it was created. In this case, it is the first custom field created, so it is accessed as 'customFields.decimal1' in the API.

Features:
- Exponential backoff retry logic
- Text file logging
- Dry run mode
- Secrets loaded from external file
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
                      initial_delay: float = 1.0, **kwargs) -> requests.Response:
        """
        Make an HTTP request with exponential backoff retry logic.
        
        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            url: URL to request
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay in seconds before first retry
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            requests.Response: The response object if successful
            
        Raises:
            Exception: If all retries are exhausted, an exception is always raised
                      rather than returning a response
        """
        delay = initial_delay
        last_error = None
        
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
        
        for attempt in range(max_retries):
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
                
                # If we get a rate limit or server error, retry
                if response.status_code in [429, 500, 502, 503, 504]:
                    if attempt < max_retries - 1:
                        logging.warning(
                            f"Retry {attempt + 1}/{max_retries} for {method} {url} "
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
                
                return response
                
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                if self.debug:
                    logging.info(f"DEBUG: Request Exception: {last_error}")
                if attempt < max_retries - 1:
                    logging.warning(
                        f"Retry {attempt + 1}/{max_retries} for {method} {url} "
                        f"(error: {last_error})"
                    )
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    raise Exception(f"Max retries exceeded: {last_error}")
            
    def get_users_incremental(self, page_size: int = 500, csv_file: str = None, filter_blank: bool = False) -> int:
        """
        Retrieve all users from Absorb LMS with pagination and save to CSV incrementally.
        
        Args:
            page_size: Number of users to retrieve per page (default: 500)
            csv_file: Path to CSV file to save users incrementally
            filter_blank: If True, only retrieve users where customFields/decimal1 is null
            
        Returns:
            Total number of users with externalId retrieved
        """
        page = 0  # Page number (0-indexed)
        total_items = None
        total_pages = None
        users_with_external_id = 0
        
        # Open CSV file and write header
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Status', 'id', 'username', 'externalId', 'current_decimal1', 'user_data_json'])
            
            while True:
                url = f"{self.api_url}/users"
                params = {
                    "_limit": page_size,
                    "_offset": page  # Page number, not offset by page_size
                }
                
                # Add filter for blank decimal1 if requested
                if filter_blank:
                    params["_filter"] = "customFields/decimal1 eq null"
                
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
                            external_id = user.get('externalId', '')
                            
                            # Skip users without externalId
                            if not external_id:
                                continue
                            
                            # Get current decimal1 value
                            custom_fields = user.get('customFields') or {}
                            current_decimal1 = custom_fields.get('decimal1', '')
                            
                            # Store entire user data as JSON for PUT later
                            user_data_json = json.dumps(user)
                            
                            writer.writerow(['Retrieved', user_id, username, external_id, current_decimal1, user_data_json])
                            batch_count += 1
                            users_with_external_id += 1
                        
                        # Flush to ensure data is written to disk after each batch
                        f.flush()
                        
                        current_batch = page + 1
                        logging.info(f"Downloading user batch {current_batch} of {total_pages} ({len(page_users)} users, {batch_count} with externalId)")
                        
                        page += 1  # Increment page number by 1
                        
                        # Check if we've retrieved all users based on returned count
                        if len(page_users) < page_size:
                            break
                    else:
                        logging.error(f"Failed to retrieve users: {response.status_code} - {response.text}")
                        break
                        
                except Exception as e:
                    logging.error(f"Error retrieving users: {str(e)}")
                    break
        
        logging.info(f"Total users with externalId saved to CSV: {users_with_external_id}")
        return users_with_external_id
    
    def update_user(self, user_data: Dict[str, Any], external_id: str) -> bool:
        """
        Update a user's customFields.decimal1 with the externalId value.
        
        Args:
            user_data: Complete user data dictionary
            external_id: External ID value to set in customFields.decimal1
            
        Returns:
            bool: True if update successful, False otherwise
        """
        user_id = user_data.get('id')
        url = f"{self.api_url}/users/{user_id}"
        
        try:
            # Update customFields.decimal1 with the externalId
            if 'customFields' not in user_data or user_data['customFields'] is None:
                user_data['customFields'] = {}
            
            # Convert externalId to float for decimal1
            try:
                decimal_value = float(external_id)
            except (ValueError, TypeError):
                logging.warning(f"Cannot convert externalId '{external_id}' to decimal for user {user_id}")
                return False
            
            user_data['customFields']['decimal1'] = decimal_value
            
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
            
            if response.status_code in [200, 204]:
                return True
            else:
                logging.error(
                    f"Failed to update user {user_id}: {response.status_code} - {response.text}"
                )
                return False
                
        except Exception as e:
            logging.error(f"Error updating user {user_id}: {str(e)}")
            return False


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


def sync_external_ids(client: AbsorbLMSClient, dry_run: bool = False, csv_file: str = None, 
                      filter_blank: bool = False, overwrite: bool = False, 
                      use_existing_file: bool = False) -> tuple:
    """
    Sync external IDs from 'externalId' field to 'customFields.decimal1' field.
    
    Args:
        client: Authenticated AbsorbLMSClient instance
        dry_run: If True, only simulate the sync without making changes
        csv_file: Path to CSV file for storing user data
        filter_blank: If True, only process users with null decimal1
        overwrite: If True, update even if decimal1 already has a value
        use_existing_file: If True, skip download and use existing CSV file
        
    Returns:
        Tuple of (success_count, error_count, skip_count)
    """
    if csv_file is None:
        csv_file = f'users_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    logging.info("Starting external ID sync...")
    
    if dry_run:
        logging.info("DRY RUN MODE - No changes will be made")
    
    if filter_blank:
        logging.info("Filtering for users with null/empty decimal1 field only")
    
    if not overwrite:
        logging.info("Will skip users where externalId doesn't match existing decimal1 value (marked as 'Different')")
    
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
        users_count = client.get_users_incremental(page_size=500, csv_file=csv_file, filter_blank=filter_blank)
    
    if users_count == 0:
        logging.warning("No users with externalId found. Exiting.")
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
    
    # Read CSV, process each user, and update CSV incrementally
    temp_csv = None
    temp_dir = os.path.dirname(csv_file) or '.'
    with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=temp_dir, suffix='.tmp', newline='', encoding='utf-8') as temp_file:
        temp_csv = temp_file.name
    
    try:
        with open(csv_file, 'r', newline='', encoding='utf-8') as f_in, \
             open(temp_csv, 'w', newline='', encoding='utf-8') as f_out:
            
            reader = csv.DictReader(f_in)
            fieldnames = reader.fieldnames
            writer = csv.DictWriter(f_out, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in reader:
                user_id = row['id']
                username = row['username']
                external_id = row['externalId']
                current_decimal1 = row.get('current_decimal1', '')
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
                
                # Check if we should skip this user based on overwrite flag
                # Remove decimals from decimal1 for comparison (externalId is always whole number)
                current_decimal1_int = None
                if current_decimal1:
                    try:
                        current_decimal1_int = int(float(current_decimal1))
                    except (ValueError, TypeError):
                        current_decimal1_int = None
                
                external_id_int = None
                try:
                    external_id_int = int(external_id)
                except (ValueError, TypeError):
                    external_id_int = None
                
                # Skip if values don't match and overwrite is False
                if not overwrite and current_decimal1_int is not None and current_decimal1_int != external_id_int:
                    logging.info(f"Skipping user {username} (ID: {user_id}) - External ID: {external_id}, Current decimal1: {current_decimal1} (different values)")
                    row['Status'] = 'Different'
                    skip_count += 1
                    writer.writerow(row)
                    f_out.flush()
                    continue
                
                logging.info(f"Processing user {username} (ID: {user_id}) - External ID: {external_id}")
                
                if dry_run:
                    logging.info(f"[DRY RUN] Would update customFields.decimal1 to: {external_id}")
                    row['Status'] = 'Success'
                    success_count += 1
                else:
                    if client.update_user(user_data, external_id):
                        logging.info(f"Successfully updated user {username}")
                        row['Status'] = 'Success'
                        success_count += 1
                    else:
                        logging.error(f"Failed to update user {username}")
                        row['Status'] = 'Failure'
                        error_count += 1
                
                writer.writerow(row)
                f_out.flush()  # Flush after each row to ensure it's written to disk
            
            # Replace original CSV with updated one
            if not dry_run:
                os.replace(temp_csv, csv_file)
                logging.info(f"Updated CSV saved to {csv_file}")
            else:
                # In dry-run, remove temp file
                if os.path.exists(temp_csv):
                    os.remove(temp_csv)
    
    except Exception as e:
        logging.error(f"Error during processing: {e}")
        # Clean up temp file on error
        if temp_csv and os.path.exists(temp_csv):
            os.remove(temp_csv)
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
        description='Sync external IDs from External ID field to Ext_ID field in Absorb LMS'
    )
    parser.add_argument(
        '--secrets',
        default='secrets.txt',
        help='Path to secrets file (default: secrets.txt)'
    )
    parser.add_argument(
        '--log-file',
        default=None,
        help='Path to log file (default: logs/absorb_sync_YYYYMMDD_HHMMSS.log)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run in dry-run mode (no changes will be made)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode (prints sensitive data including API keys)'
    )
    parser.add_argument(
        '--csv-file',
        default=None,
        help='Path to CSV file for storing user data (default: users_YYYYMMDD_HHMMSS.csv)'
    )
    parser.add_argument(
        '--blank',
        action='store_true',
        help='Filter only users that have a null/empty value for decimal1 field'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Update customFields.decimal1 even if it already has a value'
    )
    parser.add_argument(
        '--update',
        action='store_true',
        help='Actually perform updates (default is dry-run mode unless --update is specified)'
    )
    parser.add_argument(
        '--file',
        default=None,
        help='Path to existing CSV file to process (skips download phase)'
    )
    
    args = parser.parse_args()
    
    # Handle dry-run vs update flag precedence
    # If --update is specified, disable dry-run (unless --dry-run is also explicitly set)
    if args.update and not args.dry_run:
        args.dry_run = False
    elif not args.update:
        # Default to dry-run mode if --update is not specified
        args.dry_run = True
    # If both --dry-run and --update are specified, --dry-run takes precedence
    
    # Generate default log file name at runtime if not specified
    if args.log_file is None:
        args.log_file = f'logs/absorb_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    
    # Set up logging
    setup_logging(args.log_file)
    
    logging.info("="*60)
    logging.info("Absorb LMS External ID Sync")
    logging.info("="*60)
    
    try:
        # Determine CSV file path
        csv_file_path = args.file if args.file else args.csv_file
        use_existing_file = args.file is not None
        
        # Load secrets and authenticate (needed for both download and update)
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
        
        # Sync external IDs
        success_count, error_count, skip_count = sync_external_ids(
            client, 
            dry_run=args.dry_run,
            csv_file=csv_file_path,
            filter_blank=args.blank,
            overwrite=args.overwrite,
            use_existing_file=use_existing_file
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
