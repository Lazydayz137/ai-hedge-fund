# Database Setup Guide

This guide covers the database architecture and setup for production trading with the AI Hedge Fund.

## Overview

The AI Hedge Fund uses PostgreSQL for persistent storage of:
- Portfolio state (cash, margin, positions)
- Trade history (immutable audit trail)
- Agent decisions and signals
- Performance metrics
- System logs

## Table of Contents
- [Quick Start](#quick-start)
- [Database Schema](#database-schema)
- [Setup Instructions](#setup-instructions)
- [Migrations](#migrations)
- [Repository Pattern](#repository-pattern)
- [Production Considerations](#production-considerations)

---

## Quick Start

### 1. Install PostgreSQL

**macOS (Homebrew):**
```bash
brew install postgresql@15
brew services start postgresql@15
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**Windows:**
Download and install from [postgresql.org](https://www.postgresql.org/download/windows/)

### 2. Create Database

```bash
# Connect to PostgreSQL
psql postgres

# Create database and user
CREATE DATABASE ai_hedge_fund;
CREATE USER hedge_fund_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE ai_hedge_fund TO hedge_fund_user;

# Exit psql
\q
```

### 3. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and set DATABASE_URL
DATABASE_URL=postgresql://hedge_fund_user:your_secure_password@localhost:5432/ai_hedge_fund
```

### 4. Run Migrations

```bash
# Run database migrations
poetry run alembic upgrade head
```

### 5. Verify Setup

```bash
# Connect to database and list tables
psql -d ai_hedge_fund

# List all tables
\dt

# Expected output: portfolios, positions, trades, decisions, etc.
```

---

## Database Schema

### Core Tables

#### `portfolios`
Tracks portfolio configuration and current state.

```sql
id                  INTEGER         PRIMARY KEY
name                VARCHAR(100)    UNIQUE
initial_cash        DECIMAL(15,2)
current_cash        DECIMAL(15,2)
margin_requirement  DECIMAL(5,4)    DEFAULT 0
margin_used         DECIMAL(15,2)   DEFAULT 0
created_at          TIMESTAMP
updated_at          TIMESTAMP
```

#### `positions`
Current holdings for each ticker.

```sql
id                 INTEGER         PRIMARY KEY
portfolio_id       INTEGER         FOREIGN KEY -> portfolios.id
ticker             VARCHAR(10)
long_shares        INTEGER         DEFAULT 0
short_shares       INTEGER         DEFAULT 0
long_cost_basis    DECIMAL(15,4)   DEFAULT 0
short_cost_basis   DECIMAL(15,4)   DEFAULT 0
short_margin_used  DECIMAL(15,2)   DEFAULT 0
updated_at         TIMESTAMP

UNIQUE(portfolio_id, ticker)
```

#### `trades`
Immutable trade history (audit trail).

```sql
id              INTEGER         PRIMARY KEY
portfolio_id    INTEGER         FOREIGN KEY -> portfolios.id
ticker          VARCHAR(10)
action          VARCHAR(10)     -- buy, sell, short, cover
quantity        INTEGER
price           DECIMAL(15,4)
total_value     DECIMAL(15,2)
commission      DECIMAL(10,2)   DEFAULT 0
executed_at     TIMESTAMP
decision_id     INTEGER         FOREIGN KEY -> decisions.id
created_at      TIMESTAMP
```

#### `decisions`
Hedge fund run metadata.

```sql
id              INTEGER         PRIMARY KEY
portfolio_id    INTEGER         FOREIGN KEY -> portfolios.id
run_id          UUID            UNIQUE
decision_date   DATE
tickers         TEXT[]
model_name      VARCHAR(50)
model_provider  VARCHAR(50)
status          VARCHAR(20)     -- pending, executing, completed, failed
created_at      TIMESTAMP
```

#### `agent_signals`
Individual agent analysis and signals.

```sql
id                  INTEGER         PRIMARY KEY
decision_id         INTEGER         FOREIGN KEY -> decisions.id
agent_name          VARCHAR(100)
ticker              VARCHAR(10)
signal              VARCHAR(20)     -- bullish, bearish, neutral
confidence          INTEGER         CHECK (0 <= confidence <= 100)
reasoning           TEXT
execution_time_ms   INTEGER
created_at          TIMESTAMP
```

#### `portfolio_decisions`
Final portfolio manager decisions.

```sql
id          INTEGER         PRIMARY KEY
decision_id INTEGER         FOREIGN KEY -> decisions.id
ticker      VARCHAR(10)
action      VARCHAR(10)     -- buy, sell, short, cover, hold
quantity    INTEGER
reasoning   TEXT
created_at  TIMESTAMP
```

#### `realized_gains`
Realized gains/losses for tax reporting.

```sql
id              INTEGER         PRIMARY KEY
portfolio_id    INTEGER         FOREIGN KEY -> portfolios.id
ticker          VARCHAR(10)
position_type   VARCHAR(10)     -- long or short
realized_gain   DECIMAL(15,2)
trade_id        INTEGER         FOREIGN KEY -> trades.id
created_at      TIMESTAMP
```

#### `performance_snapshots`
Daily portfolio performance tracking.

```sql
id                INTEGER         PRIMARY KEY
portfolio_id      INTEGER         FOREIGN KEY -> portfolios.id
snapshot_date     DATE
total_value       DECIMAL(15,2)
cash              DECIMAL(15,2)
long_value        DECIMAL(15,2)
short_value       DECIMAL(15,2)
realized_gains    DECIMAL(15,2)
unrealized_gains  DECIMAL(15,2)
created_at        TIMESTAMP

UNIQUE(portfolio_id, snapshot_date)
```

#### `system_logs`
Application logs for monitoring.

```sql
id          INTEGER         PRIMARY KEY
level       VARCHAR(20)     -- DEBUG, INFO, WARNING, ERROR, CRITICAL
component   VARCHAR(100)
message     TEXT
context     JSONB           -- Additional context as JSON
created_at  TIMESTAMP
```

#### `settings`
Configuration storage.

```sql
key         VARCHAR(100)    PRIMARY KEY
value       JSONB
description TEXT
updated_at  TIMESTAMP
```

---

## Setup Instructions

### Development Setup

1. **Install dependencies:**
```bash
poetry install
```

2. **Start PostgreSQL locally:**
```bash
# macOS
brew services start postgresql@15

# Linux
sudo systemctl start postgresql
```

3. **Create development database:**
```bash
createdb ai_hedge_fund
```

4. **Run migrations:**
```bash
poetry run alembic upgrade head
```

### Docker Setup

Use Docker Compose for isolated database:

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: hedge_fund_user
      POSTGRES_PASSWORD: dev_password
      POSTGRES_DB: ai_hedge_fund
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

```bash
# Start database
docker-compose up -d postgres

# Run migrations
DATABASE_URL=postgresql://hedge_fund_user:dev_password@localhost:5432/ai_hedge_fund \
  poetry run alembic upgrade head
```

---

## Migrations

### Creating New Migrations

```bash
# Auto-generate migration from model changes
poetry run alembic revision --autogenerate -m "Description of changes"

# Manually create empty migration
poetry run alembic revision -m "Description of changes"
```

### Running Migrations

```bash
# Upgrade to latest version
poetry run alembic upgrade head

# Upgrade one version
poetry run alembic upgrade +1

# Downgrade one version
poetry run alembic downgrade -1

# Downgrade to specific version
poetry run alembic downgrade <revision_id>

# Show current version
poetry run alembic current

# Show migration history
poetry run alembic history
```

### Migration Best Practices

1. **Always test migrations** on a copy of production data first
2. **Create backups** before running migrations in production
3. **Use transactions** for reversible operations
4. **Avoid data loss** - migrate data before dropping columns
5. **Test rollbacks** - ensure downgrade works

---

## Repository Pattern

The application uses the Repository pattern for database access.

### Using Repositories

```python
from sqlalchemy.orm import Session
from app.backend.database import get_db
from app.backend.database.repositories import (
    PortfolioRepository,
    TradeRepository,
    DecisionRepository,
    PerformanceRepository,
)

# In FastAPI endpoint
def create_portfolio(db: Session = Depends(get_db)):
    portfolio_repo = PortfolioRepository(db)

    # Create portfolio
    portfolio = portfolio_repo.create(
        name="My Portfolio",
        initial_cash=100000.00,
        current_cash=100000.00,
    )

    return portfolio

# In standalone script
from app.backend.database.session import get_db_context

with get_db_context() as db:
    portfolio_repo = PortfolioRepository(db)
    portfolio = portfolio_repo.get_by_name("My Portfolio")
```

### Available Repositories

**PortfolioRepository:**
- `get_with_positions(portfolio_id)` - Get portfolio with all positions
- `get_position(portfolio_id, ticker)` - Get position for ticker
- `update_position(...)` - Update or create position
- `update_cash(portfolio_id, cash_delta)` - Update cash balance
- `get_total_value(portfolio_id, current_prices)` - Calculate total value

**TradeRepository:**
- `create_trade(...)` - Record a trade
- `get_portfolio_trades(portfolio_id)` - Get all trades
- `get_ticker_trades(portfolio_id, ticker)` - Get trades for ticker
- `record_realized_gain(...)` - Record realized gain/loss
- `get_total_realized_gains(portfolio_id)` - Get total gains

**DecisionRepository:**
- `create_decision(...)` - Create decision record
- `add_agent_signal(...)` - Add agent signal
- `add_portfolio_decision(...)` - Add portfolio manager decision
- `get_with_signals(decision_id)` - Get decision with all signals
- `get_recent_decisions(portfolio_id)` - Get recent decisions

**PerformanceRepository:**
- `create_snapshot(...)` - Create daily snapshot
- `get_latest_snapshot(portfolio_id)` - Get most recent snapshot
- `get_snapshots_by_date_range(...)` - Get historical snapshots
- `calculate_return_since_inception(portfolio_id)` - Calculate returns
- `calculate_period_return(portfolio_id, start, end)` - Period returns

---

## Production Considerations

### Security

1. **Use strong passwords** for database users
2. **Limit network access** - firewall rules for PostgreSQL port
3. **Use SSL/TLS** for database connections
4. **Store credentials securely** - use environment variables, not code
5. **Regular security updates** for PostgreSQL

### Performance

1. **Connection pooling** is configured (10 connections by default)
2. **Indexes** are created on frequently queried columns
3. **Vacuum regularly** to maintain performance:
   ```bash
   # Run in PostgreSQL
   VACUUM ANALYZE;
   ```
4. **Monitor query performance**:
   ```bash
   # Enable slow query logging in postgresql.conf
   log_min_duration_statement = 1000  # Log queries > 1 second
   ```

### Backup Strategy

1. **Daily full backups:**
```bash
# Backup database
pg_dump ai_hedge_fund > backup_$(date +%Y%m%d).sql

# Backup with compression
pg_dump ai_hedge_fund | gzip > backup_$(date +%Y%m%d).sql.gz
```

2. **Automated backup script:**
```bash
#!/bin/bash
# backup.sh
BACKUP_DIR="/path/to/backups"
DATE=$(date +%Y%m%d_%H%M%S)
pg_dump ai_hedge_fund | gzip > "$BACKUP_DIR/ai_hedge_fund_$DATE.sql.gz"

# Keep only last 30 days
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +30 -delete
```

3. **Test restore procedures monthly:**
```bash
# Restore from backup
gunzip < backup_20250114.sql.gz | psql ai_hedge_fund_test
```

### Monitoring

1. **Enable logging:**
```ini
# postgresql.conf
logging_collector = on
log_directory = 'pg_log'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_statement = 'mod'  # Log all modifications
```

2. **Monitor connections:**
```sql
-- Current connections
SELECT * FROM pg_stat_activity;

-- Connection count by database
SELECT datname, count(*)
FROM pg_stat_activity
GROUP BY datname;
```

3. **Monitor table sizes:**
```sql
-- Table sizes
SELECT
    tablename,
    pg_size_pretty(pg_total_relation_size(tablename::text)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(tablename::text) DESC;
```

### Scaling

For high-frequency trading or large portfolios:

1. **Read replicas** for analytics queries
2. **Partitioning** for `trades` and `system_logs` tables
3. **TimescaleDB** extension for time-series data
4. **Connection pooling** with PgBouncer

---

## Troubleshooting

### Cannot connect to database

```bash
# Check PostgreSQL is running
pg_isready

# Check connection settings
psql $DATABASE_URL

# Check pg_hba.conf allows connections
# Edit /etc/postgresql/<version>/main/pg_hba.conf
```

### Migration fails

```bash
# Check current version
poetry run alembic current

# Check history
poetry run alembic history

# Force to specific version (use with caution)
poetry run alembic stamp <revision_id>
```

### Performance issues

```sql
-- Find slow queries
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Check for missing indexes
SELECT schemaname, tablename, attname, n_distinct
FROM pg_stats
WHERE schemaname = 'public'
  AND n_distinct > 100
ORDER BY n_distinct DESC;
```

---

## Next Steps

1. **Run migrations** to create tables
2. **Create your first portfolio** using the repository
3. **Set up automated backups**
4. **Configure monitoring**
5. **Run paper trading** to validate database operations

For questions or issues, see the main [README.md](README.md).
