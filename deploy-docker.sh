#!/bin/bash
# Docker Deployment Script for Rental Listings Scraper

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first:"
        echo "  curl -fsSL https://get.docker.com -o get-docker.sh"
        echo "  sudo sh get-docker.sh"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose:"
        echo "  sudo apt-get install docker-compose-plugin"
        exit 1
    fi
}

# Check if config.yaml exists and is configured
check_config() {
    if [ ! -f "config.yaml" ]; then
        log_error "config.yaml not found. Please ensure config.yaml exists."
        exit 1
    fi

    # Basic validation - check for placeholder emails
    if grep -q "your-email@gmail.com\|replace-with-your-email" config.yaml; then
        log_warning "config.yaml appears to contain placeholder email addresses."
        log_warning "Please edit config.yaml with your actual email settings."
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Please update config.yaml and run this script again."
            exit 1
        fi
    fi
}

# Create necessary directories
create_directories() {
    log_info "Creating necessary directories..."
    mkdir -p data logs backups
    log_success "Directories created"
}

# Build and deploy
deploy() {
    log_info "Building Docker image..."
    docker-compose build

    log_info "Starting rental scraper service..."
    docker-compose up -d

    log_info "Waiting for service to start..."
    sleep 5

    # Check if container is running
    if docker-compose ps | grep -q "rental-scraper"; then
        log_success "Rental scraper deployed successfully!"

        # Show status
        echo
        log_info "Service Status:"
        docker-compose ps

        echo
        log_info "Recent Logs:"
        docker-compose logs --tail=10 rental-scraper

        echo
        log_info "Useful commands:"
        echo "  docker-compose logs -f rental-scraper    # Follow logs"
        echo "  docker-compose restart rental-scraper    # Restart service"
        echo "  docker-compose down                      # Stop service"
        echo "  # Manual backup: docker run --rm -v \$(pwd)/data:/app/data -v \$(pwd)/backups:/app/backups rental-scraper sh -c 'tar -czf /app/backups/backup_\$(date +%Y%m%d_%H%M%S).tar.gz /app/data'"

    else
        log_error "Service failed to start. Check logs:"
        docker-compose logs rental-scraper
        exit 1
    fi
}

# Main deployment flow
main() {
    log_info "🐳 Docker Deployment for Rental Listings Scraper"
    echo

    check_docker
    check_config
    create_directories
    deploy

    echo
    log_success "🎉 Deployment complete!"
    log_info "Your rental scraper is now running and will send email notifications for new listings."
}

# Handle command line arguments
case "${1:-}" in
    "stop")
        log_info "Stopping rental scraper..."
        docker-compose down
        log_success "Service stopped"
        ;;
    "restart")
        log_info "Restarting rental scraper..."
        docker-compose restart rental-scraper
        log_success "Service restarted"
        ;;
    "logs")
        docker-compose logs -f rental-scraper
        ;;
    "status")
        log_info "Service Status:"
        docker-compose ps
        echo
        log_info "Container Health:"
        docker stats --no-stream rental-scraper
        ;;
    "backup")
        log_info "Creating backup..."
        mkdir -p backups
        docker run --rm \
            -v "$(pwd)/data:/app/data:ro" \
            -v "$(pwd)/backups:/app/backups" \
            rental-scraper \
            sh -c "tar -czf /app/backups/backup_\$(date +%Y%m%d_%H%M%S).tar.gz /app/data && echo 'Backup completed'"
        ;;
    "help"|"-h"|"--help")
        echo "Docker Deployment Script for Rental Listings Scraper"
        echo
        echo "Usage: $0 [command]"
        echo
        echo "Commands:"
        echo "  (no command)  Deploy the service"
        echo "  stop          Stop the service"
        echo "  restart       Restart the service"
        echo "  logs          Follow service logs"
        echo "  status        Show service status"
        echo "  backup        Create a data backup"
        echo "  help          Show this help"
        ;;
    *)
        main
        ;;
esac
