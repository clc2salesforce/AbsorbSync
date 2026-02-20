# AbsorbSync

Synchronize user data between fields in Absorb LMS. By default, syncs from `externalId` to `customFields.decimal1` (Associate Number), but can be configured to sync from any source field to any target custom field using the `--sourceField` and `--customField` flags.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Quick Start](#quick-start)
  - [Command Line Options](#command-line-options)
  - [Usage Examples](#usage-examples)
- [Filtering Options](#filtering-options)
- [Validation and Behavior](#validation-and-behavior)
- [Status Values](#status-values)
- [CSV Files](#csv-files)
- [Logging](#logging)
- [Performance and Fault Tolerance](#performance-and-fault-tolerance)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

## Features

### Core Functionality
- Downloads values from any source field (default: `externalId`) in Absorb LMS user accounts
- Uploads values to a configurable custom field (default: `customFields.decimal1` Associate Number field)
- Supports syncing from standard user fields (e.g., `externalId`, `username`, `emailAddress`) or custom fields (e.g., `customFields.string1`)
- Supports custom field types: `decimal*` (converted to float) and `string*` (kept as string)
- Also supports `date*` and `checkbox*` fields (treated as strings)
- Requires `--update` flag for actual changes (default is dry-run mode)
- Incremental CSV export for fault tolerance
- User confirmation before processing updates

### API Integration
- Absorb LMS REST API v2 authentication
- Exponential backoff retry logic for transient failures (429, 5xx errors)
- Supports 200 requests per second (no artificial delays)
- Proper pagination with page-based offsets

### Filtering and Validation
- Filter by department ID
- Filter for blank custom field values only (e.g., blank `decimal1`)
- Numeric-only validation for source field values (with `--alpha` option for alphanumeric)
- Skip or overwrite existing values
- Handles blank source field values gracefully

### Observability
- Timestamped file logging plus console output
- Debug mode for troubleshooting (prints sensitive data)
- Comprehensive status tracking in CSV files

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/clc2salesforce/AbsorbSync.git
   cd AbsorbSync
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your credentials:**
   ```bash
   cp secrets.txt.example secrets.txt
   # Edit secrets.txt with your Absorb LMS API credentials
   ```

## Configuration

Edit `secrets.txt` with your Absorb LMS API credentials:

```
ABSORB_API_URL=https://rest.sandbox.myabsorb.com
ABSORB_API_KEY=your-api-key-guid
ABSORB_API_USERNAME=your_username
ABSORB_API_PASSWORD=your_password
```

### Credentials Explained

- **ABSORB_API_URL**: Base URL for your Absorb LMS REST API (e.g., `https://rest.sandbox.myabsorb.com` or `https://rest.myabsorb.com`)
- **ABSORB_API_KEY**: API key GUID used for both the `x-api-key` header and `privateKey` in authentication
- **ABSORB_API_USERNAME**: Username for API authentication
- **ABSORB_API_PASSWORD**: Password for API authentication

**Important:** Never commit `secrets.txt` to version control. It's already excluded in `.gitignore`.

## Usage

### Quick Start

```bash
# Preview changes (dry-run mode - default)
python absorb_sync.py

# Actually perform updates (requires --update flag)
python absorb_sync.py --update

# Get help
python absorb_sync.py --help
```

### Command Line Options

#### Configuration Options
- `--secrets FILE` - Path to secrets file (default: `secrets.txt`)
- `--log-file FILE` - Path to log file (default: `logs/absorb_sync_YYYYMMDD_HHMMSS.log`)
- `--csv-file FILE` - Path to CSV file for user data (default: `users_YYYYMMDD_HHMMSS.csv`)
- `--customField FIELD` - Target custom field name (default: `decimal1`). Specify only the field name without the `customFields` prefix. Examples: `decimal1`, `decimal2`, `string1`, `string2`, `date1`, `checkbox1`. The script validates that field names match the standard Absorb LMS pattern (e.g., `decimal1`, `string1`) and warns if an unusual field name is provided. Users should verify the field exists in their Absorb LMS instance before running.
- `--sourceField FIELD` - Source field to sync from (default: `externalId`). Can be any field from the user object (e.g., `externalId`, `username`, `emailAddress`) or a nested field like `customFields.string1`. For custom fields, specify the full path (e.g., `customFields.decimal1`).

#### Processing Mode Options
- `--update` - Actually perform updates (default is dry-run mode)
- `--dry-run` - Explicitly enable dry-run mode (no changes made, this is the default)
- `--file FILE` - Process existing CSV file instead of downloading from API

#### Filtering Options
- `--blank` - Filter to only users with null/empty target custom field (e.g., `decimal1` by default)
- `--department DEPT_ID` - Filter by departmentId UUID

#### Validation and Behavior Options
- `--overwrite` - Update custom field even if it has a different value (default: skip and mark as "Different")
- `--alpha` - Allow alphanumeric source field values (default: numeric only, non-numeric marked as "Wrong Format")

#### Debug Options
- `--debug` - Enable debug mode (prints sensitive data including API keys - USE ONLY IN SANDBOX)

### Usage Examples

#### Basic Operations

```bash
# Dry-run to preview changes (default behavior)
python absorb_sync.py

# Perform actual updates
python absorb_sync.py --update

# Use custom configuration files
python absorb_sync.py --secrets prod_secrets.txt --log-file logs/production.log --update

# Sync to a different custom field
python absorb_sync.py --customField string1 --update

# Sync to decimal2 instead of decimal1
python absorb_sync.py --customField decimal2 --update

# Sync from a different source field (e.g., username to string1)
python absorb_sync.py --sourceField username --customField string1 --update

# Sync from one custom field to another (e.g., string2 to decimal1)
python absorb_sync.py --sourceField customFields.string2 --customField decimal1 --update
```

#### Filtering Examples

```bash
# Only update users with blank custom field (default: decimal1)
python absorb_sync.py --blank --update

# Filter by specific department
python absorb_sync.py --department c458459d-2f86-4c66-a481-e17e6983f7ee --update

# Combine filters: blank custom field in specific department
python absorb_sync.py --blank --department c458459d-2f86-4c66-a481-e17e6983f7ee --update

# Only update users with blank string1 field
python absorb_sync.py --customField string1 --blank --update
```

#### Validation Examples

```bash
# Allow alphanumeric source values (default is numeric only)
python absorb_sync.py --alpha --update

# Overwrite existing decimal1 values even if different
python absorb_sync.py --overwrite --update

# Combine: allow alphanumeric and overwrite existing values
python absorb_sync.py --alpha --overwrite --update
```

#### Advanced Examples

```bash
# Process existing CSV file (skip download)
python absorb_sync.py --file users_20260219_123456.csv --update

# Debug mode for troubleshooting (prints API keys in cleartext)
python absorb_sync.py --debug --dry-run

# Complete example: filter, validate, and update specific department
python absorb_sync.py \
  --department c458459d-2f86-4c66-a481-e17e6983f7ee \
  --blank \
  --alpha \
  --overwrite \
  --update

# Sync to string2 field with alphanumeric values for specific department
python absorb_sync.py \
  --customField string2 \
  --department c458459d-2f86-4c66-a481-e17e6983f7ee \
  --blank \
  --alpha \
  --update

# Sync email addresses to a custom string field
python absorb_sync.py \
  --sourceField emailAddress \
  --customField string3 \
  --alpha \
  --update
```
```

## Filtering Options

### --blank Flag
Uses OData filter syntax to download only users where the target custom field is null or empty.

**OData Filter:** `_filter=customFields/{customField} eq null` (e.g., `customFields/decimal1 eq null` by default)

**Use Case:** Reduces download time for large user databases by only fetching users that need updating.

**Note:** The filter uses the field specified by `--customField` (default: `decimal1`).

### --department Flag
Filters users by department ID UUID.

**OData Filter:** `_filter=departmentId eq guid'<department-id>'`

**Example:** `--department c458459d-2f86-4c66-a481-e17e6983f7ee`

**Combining Filters:** The script combines multiple filters using the `and` operator:
```
_filter=(customFields/{customField} eq null) and (departmentId eq guid'<department-id>')
```

**Example with custom field:**
```bash
python absorb_sync.py --customField string1 --blank --department c458459d-2f86-4c66-a481-e17e6983f7ee --update
```

## Validation and Behavior

### Source Field Format Validation

By default, the script validates that source field values are numeric only.

**Without --alpha flag:**
- Only numeric source field values are processed
- Non-numeric values are marked as "Wrong Format" and skipped

**With --alpha flag:**
- Alphanumeric source field values are allowed
- All non-blank source field values are processed

### Blank Source Field Handling

**Case 1: Blank source field, blank target custom field**
- User is silently skipped (no action needed)

**Case 2: Blank source field, populated target custom field**
- User is marked as "Different" and skipped
- Prevents accidentally clearing populated fields

### Overwrite Behavior

**Without --overwrite flag (default):**
- If source field value doesn't match the target custom field value (after removing decimals for decimal fields), user is marked as "Different" and skipped
- Only updates users where the target custom field is blank or matches the source field value

**With --overwrite flag:**
- All users are updated regardless of current custom field value
- Existing different values are replaced

**Comparison Logic:**
- For decimal fields: Decimals are removed before comparison (e.g., `8675309.00` → `8675309`)
- For string/date/checkbox fields: Direct string comparison is performed
- Source field value is compared as-is (numeric by default, alphanumeric with `--alpha`)

**Field Type Handling:**
- Decimal fields (`decimal1`, `decimal2`, etc.): Values are converted to float type
- String/date/checkbox fields: Values are kept as strings

## Status Values

The CSV file tracks processing status for each user:

| Status | Description |
|--------|-------------|
| **Retrieved** | User downloaded from API, not yet processed |
| **Success** | User successfully updated in Absorb LMS |
| **Failure** | Update failed (error logged) |
| **Different** | Skipped because source field value doesn't match the target custom field (when --overwrite not used), OR source field is blank but the target custom field is populated |
| **Wrong Format** | Source field value contains non-numeric characters (when --alpha not used) |

## CSV Files

### Automatic Generation

CSV files are automatically created with timestamped names:
```
users_20260219_123456.csv
```

### CSV Columns

- **Status** - Processing status (Retrieved, Success, Failure, Different, Wrong Format)
- **id** - User UUID
- **username** - Username
- **Source field column** - The column name matches the source field specified with `--sourceField`. For example:
  - If using `--sourceField externalId` (default), the column is named `externalId`
  - If using `--sourceField username`, the column is named `username`
  - If using `--sourceField customFields.string1`, the column is named `customFields.string1`
- **Target field column** - The column name follows the pattern `current_{field}` where `{field}` is the custom field specified with `--customField`. For example:
  - If using `--customField decimal1` (default), the column is named `current_decimal1`
  - If using `--customField string1`, the column is named `current_string1`
- **user_data_json** - Complete user profile as JSON (needed for PUT updates)

### Incremental Updates

- CSV is written **incrementally after each batch** during download (with disk flush)
- Status column is updated **after each user** during processing (with disk flush)
- If the script fails, the CSV shows exactly where it stopped

### Reprocessing CSV Files

Use the `--file` flag to process an existing CSV file:

```bash
python absorb_sync.py --file users_20260219_123456.csv --update
```

This skips the download phase and processes users from the CSV file.

## Logging

### Log Files

Logs are written to both:
- **Console** (stdout) - Real-time progress
- **Log file** - Persistent audit trail

Default log file location: `logs/absorb_sync_YYYYMMDD_HHMMSS.log`

### Log Contents

- Authentication status
- Download progress (batch X of Y)
- User confirmation prompts
- Update progress
- Success/failure counts
- Error messages and stack traces

### Debug Mode

Enable with `--debug` flag:

```bash
python absorb_sync.py --debug --dry-run
```

**Debug output includes:**
- API URL
- API key (cleartext)
- Username (cleartext)
- Password (cleartext)
- HTTP request details (method, URL, headers, body)
- HTTP response details (status, headers, body)

⚠️ **WARNING:** Debug mode prints sensitive data in cleartext. Use only in sandbox environments.

## Performance and Fault Tolerance

### High Performance

- **No artificial delays** between successful API requests
- Only exponential backoff on failures (429, 5xx errors)
- Supports Absorb API's **200 requests per second** limit
- Default page size: **500 users per batch**

### Fault Tolerance

**Incremental CSV Writing:**
- CSV flushed to disk after each batch during download
- Status updates flushed to disk after each user during processing
- If script crashes, CSV shows exact progress

**Resume Capability:**
- Use `--file` flag to reprocess an existing CSV file
- Useful for resuming after failures or network interruptions

**Exponential Backoff:**
- Automatic retry for transient failures
- Exponential backoff: 1s → 2s → 4s → 8s → 16s
- Maximum 5 retry attempts per request

### User Confirmation

Before processing updates, the script:
1. Downloads all users matching filters
2. Exports to CSV file
3. Displays total user count
4. Prompts: "Do you want to proceed with updating X users? (yes/y/no)"
5. Only proceeds if user confirms

## Security

### Credentials Management

- API credentials stored in separate `secrets.txt` file
- Secrets file excluded from version control via `.gitignore`
- Use `secrets.txt.example` as a template (safe to commit)

### API Authentication

The script implements Absorb LMS REST API v2 authentication:

1. POST to `/authenticate` endpoint with:
   - `username`
   - `password`
   - `privateKey` (same value as API key)
2. Receive authentication token
3. Use token in `Authorization` header for subsequent requests
4. Include `x-api-key` header on all requests

### Best Practices

- Never commit `secrets.txt` to version control
- Use `--debug` only in sandbox environments
- Rotate API credentials regularly
- Use dry-run mode before production updates
- Review CSV files before confirming updates

## Troubleshooting

### Authentication Errors

**Error:** "Invalid API key"

**Solution:**
- Verify `ABSORB_API_KEY` in `secrets.txt` is correct
- Ensure you're using the correct API URL (sandbox vs production)
- Check that all four credentials are provided

### No Users Found

**Error:** "Found 0 users"

**Solution:**
- Check your filter criteria (--blank, --department)
- Verify users exist matching your filters
- Try without filters to see all users
- Use `--debug` to see API responses

### Wrong Format Errors

**Error:** Many users marked as "Wrong Format"

**Solution:**
- Source field values contain non-numeric characters
- Use `--alpha` flag to allow alphanumeric values:
  ```bash
  python absorb_sync.py --alpha --update
  ```

### Rate Limiting

**Error:** 429 Too Many Requests

**Solution:**
- Script automatically handles rate limiting with exponential backoff
- If errors persist, check Absorb LMS API limits
- Consider reducing `page_size` in code (currently 500)

### Script Interruption

**Issue:** Script stopped during long-running operation

**Solution:**
1. Check the CSV file - it shows where the script stopped
2. For download interruption:
   - Re-run the script (it will create a new CSV)
3. For processing interruption:
   - Use `--file` flag to resume:
   ```bash
   python absorb_sync.py --file users_20260219_123456.csv --update
   ```

### Debug Mode

For any issues, enable debug mode to see detailed API communication:

```bash
python absorb_sync.py --debug --dry-run
```

This will show:
- Loaded configuration
- All HTTP requests (headers, body, URL)
- All HTTP responses (status, headers, body)

**Note:** Debug mode prints API keys in cleartext - use only in sandbox.