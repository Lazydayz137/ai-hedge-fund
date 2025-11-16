#!/bin/bash
# Startup script for AI Hedge Fund
# This script initializes and starts the complete system

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Print header
echo "============================================================"
echo "     AI Hedge Fund - Production Trading System"
echo "============================================================"
echo ""

# Check prerequisites
print_info "Checking prerequisites..."

if ! command_exists poetry; then
    print_error "Poetry not found. Please install: https://python-poetry.org/docs/#installation"
    exit 1
fi
print_info "✓ Poetry found"

if ! command_exists psql; then
    print_warning "PostgreSQL client not found. Database checks will be limited."
else
    print_info "✓ PostgreSQL client found"
fi

# Check for .env file
if [ ! -f ".env" ]; then
    print_warning ".env file not found"
    if [ -f ".env.example" ]; then
        print_info "Creating .env from .env.example..."
        cp .env.example .env
        print_warning "Please edit .env and add your API keys before continuing"
        print_info "Required: At least one LLM provider API key"
        exit 1
    else
        print_error ".env.example not found"
        exit 1
    fi
else
    print_info "✓ .env file found"
fi

# Load environment variables
export $(grep -v '^#' .env | xargs)

# Check DATABASE_URL
if [ -z "$DATABASE_URL" ]; then
    print_error "DATABASE_URL not set in .env"
    exit 1
fi
print_info "✓ DATABASE_URL configured"

# Check for at least one LLM API key
has_llm_key=false
if [ -n "$OPENAI_API_KEY" ] || [ -n "$ANTHROPIC_API_KEY" ] || [ -n "$GROQ_API_KEY" ] || [ -n "$DEEPSEEK_API_KEY" ] || [ -n "$GOOGLE_API_KEY" ]; then
    has_llm_key=true
fi

if [ "$has_llm_key" = false ]; then
    print_error "No LLM API key found. Please set at least one in .env:"
    echo "  - OPENAI_API_KEY"
    echo "  - ANTHROPIC_API_KEY"
    echo "  - GROQ_API_KEY"
    echo "  - DEEPSEEK_API_KEY"
    echo "  - GOOGLE_API_KEY"
    exit 1
fi
print_info "✓ LLM API key configured"

# Install dependencies
print_info ""
print_info "Installing Python dependencies..."
poetry install --no-root

# Check database connection
print_info ""
print_info "Checking database connection..."

if command_exists psql; then
    if psql "$DATABASE_URL" -c "SELECT 1" > /dev/null 2>&1; then
        print_info "✓ Database connection successful"
    else
        print_error "Cannot connect to database"
        print_info "Please ensure PostgreSQL is running and DATABASE_URL is correct"
        exit 1
    fi
fi

# Run database initialization
print_info ""
print_info "Initializing database..."
poetry run python scripts/init_db.py

# Run tests (optional)
read -p "Run tests before starting? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Running tests..."
    poetry run pytest tests/unit/ -v
    print_info "✓ Tests passed"
fi

# Success
echo ""
echo "============================================================"
print_info "✓ System initialized successfully!"
echo "============================================================"
echo ""
echo "You can now run:"
echo ""
echo "  1. Standard hedge fund run:"
echo "     poetry run python src/main.py --ticker AAPL,MSFT,NVDA"
echo ""
echo "  2. With detailed reasoning:"
echo "     poetry run python src/main.py --ticker AAPL --show-reasoning"
echo ""
echo "  3. Backtesting:"
echo "     poetry run python src/backtester.py --ticker AAPL,MSFT,NVDA"
echo ""
echo "  4. Run tests:"
echo "     poetry run pytest"
echo ""
echo "For Docker deployment, see DEPLOYMENT.md"
echo ""
