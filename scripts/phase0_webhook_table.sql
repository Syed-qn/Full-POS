CREATE TABLE IF NOT EXISTS partner_webhook_deliveries (
    id BIGSERIAL PRIMARY KEY,
    restaurant_id BIGINT NOT NULL REFERENCES restaurants(id),
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    target_url VARCHAR(512) NOT NULL,
    idempotency_key VARCHAR(256) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_partner_webhook_deliveries_restaurant_id ON partner_webhook_deliveries (restaurant_id);
CREATE INDEX IF NOT EXISTS ix_partner_webhook_deliveries_event_type ON partner_webhook_deliveries (event_type);
CREATE INDEX IF NOT EXISTS ix_partner_webhook_deliveries_status ON partner_webhook_deliveries (status);
DROP TRIGGER IF EXISTS trg_partner_webhook_deliveries_updated_at ON partner_webhook_deliveries;
CREATE TRIGGER trg_partner_webhook_deliveries_updated_at BEFORE UPDATE ON partner_webhook_deliveries FOR EACH ROW EXECUTE FUNCTION set_updated_at();