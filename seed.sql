-- Sample data for the telecom project

INSERT INTO packages (name, category, internet_gb, sms_count, voice_minutes, monthly_price, is_active) VALUES
('Genc Paketi',      'combo',    20, 1000, 1000, 149.90, TRUE),
('Sinirsiz Konusma',  'mobile',   10, 500,  5000, 179.90, TRUE),
('Baslangic Paketi',  'combo',    5,  250,  250,  89.90,  TRUE),
('Premium Sinirsiz',  'combo',    100,2000, 10000,299.90, TRUE),
('Eski Ekonomik',     'mobile',   2,  100,  100,  49.90,  FALSE);

INSERT INTO customers (first_name, last_name, phone_number, national_id, city, signup_date, line_type, status) VALUES
('Ahmet',  'Yilmaz',  '5301112233', '10000000001', 'Istanbul', '2023-01-15', 'postpaid', 'active'),
('Ayse',   'Kaya',    '5302223344', '10000000002', 'Ankara',   '2023-03-22', 'prepaid',  'active'),
('Mehmet', 'Demir',   '5303334455', '10000000003', 'Izmir',    '2022-11-05', 'postpaid', 'active'),
('Fatma',  'Sahin',   '5304445566', '10000000004', 'Bursa',    '2024-02-10', 'prepaid',  'suspended'),
('Ali',    'Celik',   '5305556677', '10000000005', 'Istanbul', '2023-07-30', 'postpaid', 'active'),
('Zeynep', 'Arslan',  '5306667788', '10000000006', 'Antalya',  '2024-05-18', 'prepaid',  'active'),
('Mustafa','Aydin',   '5307778899', '10000000007', 'Ankara',   '2021-09-01', 'postpaid', 'cancelled'),
('Elif',   'Ozturk',  '5308889900', '10000000008', 'Istanbul', '2023-12-12', 'prepaid',  'active'),
('Emre',   'Kurt',    '5309990011', '10000000009', 'Izmir',    '2024-01-25', 'postpaid', 'active'),
('Merve',  'Yildiz',  '5301000022', '10000000010', 'Bursa',    '2022-06-14', 'prepaid',  'active');

INSERT INTO subscriptions (customer_id, package_id, start_date, end_date, status) VALUES
(1, 4, '2023-01-15', NULL, 'active'),
(2, 3, '2023-03-22', NULL, 'active'),
(3, 2, '2022-11-05', NULL, 'active'),
(4, 1, '2024-02-10', NULL, 'active'),
(5, 4, '2023-07-30', NULL, 'active'),
(6, 3, '2024-05-18', NULL, 'active'),
(7, 5, '2021-09-01', '2024-01-01', 'cancelled'),
(8, 1, '2023-12-12', NULL, 'active'),
(9, 1, '2024-01-25', NULL, 'active'),
(10,3, '2022-06-14', NULL, 'active');

INSERT INTO usage_records (subscription_id, period_month, internet_used_mb, sms_used, minutes_used) VALUES
(1, '2026-07-01', 85000, 120, 3200),
(2, '2026-07-01', 4800,  30,  150),
(3, '2026-07-01', 9500,  200, 4800),
(4, '2026-07-01', 6200,  90,  200),
(5, '2026-07-01', 102000,300, 5100),
(6, '2026-07-01', 4900,  20,  100),
(8, '2026-07-01', 5100,  60,  180),
(9, '2026-07-01', 3800,  10,  90),
(10,'2026-07-01', 4700,  40,  210);

INSERT INTO invoices (customer_id, period_month, amount, is_paid, due_date) VALUES
(1, '2026-07-01', 299.90, TRUE,  '2026-07-20'),
(3, '2026-07-01', 179.90, TRUE,  '2026-07-20'),
(5, '2026-07-01', 299.90, FALSE, '2026-07-20'),
(9, '2026-07-01', 199.90, TRUE,  '2026-07-20');
