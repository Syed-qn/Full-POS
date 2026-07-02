ALTER TABLE orders ADD COLUMN IF NOT EXISTS pos_order_id VARCHAR(64);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pos_pushed_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pos_push_status VARCHAR(16);
CREATE INDEX IF NOT EXISTS ix_orders_restaurant_status_created
    ON orders (restaurant_id, status, created_at);