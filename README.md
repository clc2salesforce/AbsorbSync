# AbsorbSync

Syncs external IDs from the External ID field to custom user-viewable Ext_ID field in Absorb LMS.

## Features

- Downloads 'external ID' from Absorb LMS user accounts
- Uploads the value to the same users' 'Ext_ID' custom field
- Exponential backoff retry logic for API resilience
- Text file logging for audit and debugging
- Dry run mode to preview changes without making modifications
- Secure secrets management (credentials in external file)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/clc2salesforce/AbsorbSync.git
cd AbsorbSync
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your credentials:
```bash
cp secrets.txt.example secrets.txt
# Edit secrets.txt with your Absorb LMS API credentials
```

## Configuration

Edit `secrets.txt` with your Absorb LMS API credentials:

```
ABSORB_API_URL=https://your-company.myabsorb.com/api/rest/v2
ABSORB_API_USERNAME=your_username
ABSORB_API_PASSWORD=your_password
ABSORB_API_PRIVATE_KEY=your_private_key
```

**Important:** Never commit `secrets.txt` to version control. It's already excluded in `.gitignore`.

## Usage

### Basic Usage

Run the sync with default settings:
```bash
python absorb_sync.py
```

### Dry Run Mode

Preview what changes would be made without actually updating anything:
```bash
python absorb_sync.py --dry-run
```

### Custom Secrets File

Use a different secrets file:
```bash
python absorb_sync.py --secrets /path/to/secrets.txt
```

### Custom Log File

Specify a custom log file location:
```bash
python absorb_sync.py --log-file /path/to/logfile.log
```

### All Options

```bash
python absorb_sync.py --secrets secrets.txt --log-file logs/sync.log --dry-run
```

## Command Line Options

- `--secrets`: Path to secrets file (default: `secrets.txt`)
- `--log-file`: Path to log file (default: `logs/absorb_sync_YYYYMMDD_HHMMSS.log`)
- `--dry-run`: Run in dry-run mode (no changes will be made)

## Logging

Logs are written to both:
- Console (stdout)
- Log file in the `logs/` directory (auto-created)

Each run creates a timestamped log file for easy tracking and auditing.

## Error Handling

The script includes:
- Exponential backoff retry logic for transient API failures
- Comprehensive error logging
- Graceful handling of missing external IDs
- Non-zero exit codes on errors for automation workflows

## Security

- API credentials are stored in a separate `secrets.txt` file
- The secrets file is excluded from version control via `.gitignore`
- Use `secrets.txt.example` as a template (safe to commit)

## License

This project is provided as-is for syncing Absorb LMS external IDs.
