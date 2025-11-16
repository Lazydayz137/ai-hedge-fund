# Production Deployment Guide

Complete guide for deploying the AI Hedge Fund system for real money trading.

## 🚀 Quick Start

### For Docker Users (Recommended)

```bash
# 1. Clone and setup
git clone https://github.com/yourusername/ai-hedge-fund.git
cd ai-hedge-fund

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Start all services
cd docker
docker-compose up -d postgres  # Start database
docker-compose run hedge-fund poetry run alembic upgrade head  # Run migrations
docker-compose up -d  # Start all services
```

### For Local Development

```bash
# 1. Install dependencies
poetry install

# 2. Start PostgreSQL
# macOS: brew services start postgresql@15
# Linux: sudo systemctl start postgresql

# 3. Setup database
createdb ai_hedge_fund
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/ai_hedge_fund"
poetry run alembic upgrade head

# 4. Run hedge fund
poetry run python src/main.py --ticker AAPL,MSFT,NVDA
```

---

## 📋 Prerequisites

### Required

- **Python 3.11+**
- **PostgreSQL 15+** (or Docker)
- **API Keys**:
  - At least one LLM provider (OpenAI, Anthropic, Groq, DeepSeek, or Gemini)
  - Financial Datasets API (for historical data beyond free tier)

### Optional

- Docker & Docker Compose (recommended)
- Ollama (for local LLM models)

---

## 🔧 Environment Configuration

### API Keys

```bash
# LLM Providers (need at least ONE)
OPENAI_API_KEY=sk-...              # https://platform.openai.com/
ANTHROPIC_API_KEY=sk-ant-...       # https://anthropic.com/
GROQ_API_KEY=gsk_...               # https://groq.com/
DEEPSEEK_API_KEY=sk-...            # https://deepseek.com/
GOOGLE_API_KEY=...                 # https://ai.google.dev/

# Financial Data
FINANCIAL_DATASETS_API_KEY=...     # https://financialdatasets.ai/
# Note: Free tier includes AAPL, GOOGL, MSFT, NVDA, TSLA

# Database
DATABASE_URL=postgresql://user:password@host:5432/ai_hedge_fund

# Optional: Database tuning
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_ECHO=false  # Set to "true" for SQL debugging
```

### Database Connection Strings

**Local Development:**
```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_hedge_fund
```

**Docker:**
```bash
DATABASE_URL=postgresql://hedge_fund_user:hedge_fund_pass@postgres:5432/ai_hedge_fund
```

**Production:**
```bash
# Use strong password and SSL
DATABASE_URL=postgresql://user:strong_password@db.example.com:5432/ai_hedge_fund?sslmode=require
```

---

## 🐳 Docker Deployment

### Architecture

```
docker-compose.yml:
  - postgres: PostgreSQL 15 database
  - ollama: Local LLM models (optional)
  - hedge-fund: Main trading application
  - hedge-fund-reasoning: With detailed reasoning output
  - hedge-fund-ollama: Using local Ollama models
  - backtester: Historical backtesting
  - backtester-ollama: Backtesting with Ollama
```

### Commands

```bash
# Start database only
docker-compose up -d postgres

# Run database migrations
docker-compose run hedge-fund poetry run alembic upgrade head

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f hedge-fund

# Run specific service
docker-compose run hedge-fund python src/main.py --ticker AAPL

# Stop all services
docker-compose down

# Stop and remove data (WARNING: deletes database)
docker-compose down -v
```

### Updating

```bash
# Pull latest code
git pull

# Rebuild images
docker-compose build

# Run migrations
docker-compose run hedge-fund poetry run alembic upgrade head

# Restart services
docker-compose restart
```

---

## 💻 Local Development Setup

### 1. Install Python Dependencies

```bash
# Using Poetry (recommended)
poetry install

# Or using pip
pip install -r requirements.txt
```

### 2. Setup PostgreSQL

**macOS (Homebrew):**
```bash
brew install postgresql@15
brew services start postgresql@15
createdb ai_hedge_fund
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo -u postgres createdb ai_hedge_fund
```

**Windows:**
1. Download PostgreSQL from [postgresql.org](https://www.postgresql.org/download/windows/)
2. Install and start PostgreSQL service
3. Create database using pgAdmin or psql

### 3. Run Database Migrations

```bash
# Set database URL
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/ai_hedge_fund"

# Run migrations
poetry run alembic upgrade head

# Verify
poetry run alembic current
```

### 4. Run Application

```bash
# Standard run
poetry run python src/main.py --ticker AAPL,MSFT,NVDA

# With reasoning
poetry run python src/main.py --ticker AAPL --show-reasoning

# Backtesting
poetry run python src/backtester.py --ticker AAPL,MSFT,NVDA \
  --start-date 2024-01-01 --end-date 2024-12-31
```

---

## 🧪 Testing

### Run Tests

```bash
# All tests
poetry run pytest

# Unit tests only
poetry run pytest tests/unit/

# With coverage
poetry run pytest --cov=app.backend --cov=src --cov-report=html

# Specific test file
poetry run pytest tests/unit/test_portfolio_repository.py -v
```

### Test Database

Tests use in-memory SQLite by default (no PostgreSQL required).

To test against PostgreSQL:
```bash
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/ai_hedge_fund_test"
poetry run pytest
```

---

## 📊 Database Management

### Migrations

```bash
# Create new migration (auto-generated from model changes)
poetry run alembic revision --autogenerate -m "Description of changes"

# Create empty migration
poetry run alembic revision -m "Description"

# Upgrade to latest
poetry run alembic upgrade head

# Upgrade one version
poetry run alembic upgrade +1

# Downgrade one version
poetry run alembic downgrade -1

# Show current version
poetry run alembic current

# Show history
poetry run alembic history --verbose
```

### Backup & Restore

```bash
# Backup
pg_dump ai_hedge_fund > backup_$(date +%Y%m%d).sql

# Backup with compression
pg_dump ai_hedge_fund | gzip > backup_$(date +%Y%m%d).sql.gz

# Restore
psql ai_hedge_fund < backup_20250114.sql

# Restore from compressed
gunzip < backup_20250114.sql.gz | psql ai_hedge_fund
```

### Monitoring

```bash
# Check database size
psql -d ai_hedge_fund -c "SELECT pg_size_pretty(pg_database_size('ai_hedge_fund'));"

# Check table sizes
psql -d ai_hedge_fund -c "
SELECT tablename,
       pg_size_pretty(pg_total_relation_size(tablename::text)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(tablename::text) DESC;"

# Check active connections
psql -d ai_hedge_fund -c "SELECT * FROM pg_stat_activity;"

# Vacuum and analyze
psql -d ai_hedge_fund -c "VACUUM ANALYZE;"
```

---

## 🔒 Security Best Practices

### 1. Secure Passwords

```bash
# Generate strong password
openssl rand -base64 32

# Use in DATABASE_URL
DATABASE_URL=postgresql://hedge_fund_user:$(openssl rand -base64 32)@localhost:5432/ai_hedge_fund
```

### 2. SSL/TLS Connections

```bash
# Enable SSL in postgresql.conf
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'

# Connect with SSL
DATABASE_URL=postgresql://user:pass@host:5432/db?sslmode=require
```

### 3. Firewall Configuration

```bash
# Allow only localhost
sudo ufw allow from 127.0.0.1 to any port 5432

# Or specific IP
sudo ufw allow from 192.168.1.100 to any port 5432
```

### 4. API Key Management

```bash
# Never commit .env file
echo ".env" >> .gitignore

# Use environment variables
export OPENAI_API_KEY="sk-..."

# Or use secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)
```

---

## 📈 Production Considerations

### 1. Resource Requirements

**Minimum:**
- CPU: 2 cores
- RAM: 4 GB
- Storage: 20 GB

**Recommended:**
- CPU: 4 cores
- RAM: 8 GB
- Storage: 100 GB SSD

### 2. Monitoring

Set up monitoring for:
- Database performance (slow queries, connection pool)
- API response times
- Error rates
- Trade execution success
- Portfolio reconciliation

### 3. Alerting

Configure alerts for:
- Database connection failures
- API errors (> 5% error rate)
- Trading errors
- Portfolio reconciliation failures
- Disk space < 20%

### 4. Backup Strategy

```bash
# Daily full backup
0 2 * * * pg_dump ai_hedge_fund | gzip > /backups/daily_$(date +\%Y\%m\%d).sql.gz

# Keep last 30 days
0 3 * * * find /backups -name "daily_*.sql.gz" -mtime +30 -delete

# Weekly backup to offsite storage
0 3 * * 0 pg_dump ai_hedge_fund | gzip | aws s3 cp - s3://backups/weekly_$(date +\%Y\%m\%d).sql.gz
```

### 5. Scaling

**Vertical Scaling:**
- Increase database resources (CPU, RAM)
- Use faster storage (NVMe SSD)

**Horizontal Scaling:**
- Read replicas for analytics
- Connection pooling (PgBouncer)
- Caching layer (Redis)

---

## 🆘 Troubleshooting

### Common Issues

**1. Cannot connect to database**
```bash
# Check PostgreSQL is running
pg_isready

# Check connection
psql $DATABASE_URL

# Check pg_hba.conf allows connections
sudo nano /etc/postgresql/15/main/pg_hba.conf
# Add: host all all 127.0.0.1/32 md5
sudo systemctl restart postgresql
```

**2. Migration fails**
```bash
# Check current version
poetry run alembic current

# Force to specific version (use with caution)
poetry run alembic stamp head

# Re-run migrations
poetry run alembic upgrade head
```

**3. API key errors**
```bash
# Verify .env file exists
cat .env

# Check environment variables are loaded
poetry run python -c "import os; print(os.getenv('OPENAI_API_KEY'))"

# Test API key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

**4. Out of memory**
```bash
# Check memory usage
free -h

# Reduce connection pool size in .env
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
```

**5. Slow queries**
```bash
# Enable query logging
# postgresql.conf:
log_min_duration_statement = 1000  # Log queries > 1s

# Find slow queries
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

---

## 📚 Additional Resources

- [Database Schema](DATABASE.md) - Complete schema documentation
- [Implementation Status](IMPLEMENTATION_STATUS.md) - Current completion status
- [Main README](README.md) - Project overview
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)

---

## 🎯 Next Steps

After successful deployment:

1. **Run Paper Trading** (30+ days minimum)
   - Validate decision quality
   - Test risk limits
   - Verify reconciliation

2. **Monitor Performance**
   - Daily performance snapshots
   - Agent accuracy tracking
   - Risk metrics

3. **Optimize**
   - Tune database queries
   - Adjust risk limits
   - Improve agent prompts

4. **Scale**
   - Add more tickers
   - Increase capital
   - Deploy read replicas

---

## ⚠️ CRITICAL WARNINGS

1. **NEVER skip paper trading** - Minimum 30 days required
2. **Start small** - Use 1-5% of capital initially
3. **Monitor daily** - Check for reconciliation errors
4. **Backup regularly** - Automate daily backups
5. **Test disaster recovery** - Practice restores monthly

---

**For support or questions, see the main [README.md](README.md)**
