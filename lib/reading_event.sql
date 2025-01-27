-- These are one off sql commands for Siin's reading event held on 2025-01-25

-- Get avg of Reading, VN, and Manga before the reading event since 2025.
SELECT 
   u.user_name,
   ROUND(AVG(l.amount_logged), 2) as avg_daily_amount,
   ROUND(AVG(l.time_logged), 2) as avg_daily_time
FROM logs l
JOIN users u ON l.user_id = u.discord_user_id
WHERE 
   l.media_type IN ('Reading', 'Visual Novel')
   AND DATE(l.log_date) BETWEEN '2025-01-01' AND '2025-01-24'
GROUP BY 
   u.user_name
ORDER BY 
   avg_daily_amount DESC,
   avg_daily_time DESC;


SELECT 
   u.user_name,
   ROUND(SUM(l.amount_logged), 2) as avg_daily_amount,
   ROUND(SUM(l.time_logged), 2) as avg_daily_time
FROM logs l
JOIN users u ON l.user_id = u.discord_user_id
WHERE 
   l.media_type IN ('Reading')
   AND DATE(l.log_date) = '2025-01-25'
   AND u.guild_id = 1320125298297147443
GROUP BY 
   l.user_id,
   l.media_type,
   u.user_name
ORDER BY 
   l.user_id,
   l.media_type,
   avg_daily_amount DESC,
   avg_daily_time DESC;

SELECT 
  u.user_name,
  ROUND(SUM(l.amount_logged), 2) as avg_daily_amount,
  ROUND(SUM(l.time_logged), 2) as avg_daily_time
FROM logs l
JOIN users u ON l.user_id = u.discord_user_id
WHERE 
  l.media_type IN ('Reading', 'Visual Novel')
  AND l.created_at BETWEEN '2025-01-24 11:00' AND '2025-01-26 10:00'
  AND u.guild_id = 1320125298297147443
GROUP BY 
  l.user_id,
  u.user_name
ORDER BY 
  l.user_id,
  avg_daily_amount DESC,
  avg_daily_time desc;
