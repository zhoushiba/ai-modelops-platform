-- ============================================================================
-- AI ModelOps Platform · MySQL 8 初始化脚本
-- docker compose 首次启动时由 mysql 容器自动执行（/docker-entrypoint-initdb.d）
-- 说明：业务表结构由 SQLAlchemy 在应用启动时通过 Base.metadata.create_all 创建，
--       这里只负责数据库、账号与字符集，保证多环境一致。
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `modelops`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'modelops'@'%' IDENTIFIED BY 'modelops123';
GRANT ALL PRIVILEGES ON `modelops`.* TO 'modelops'@'%';
FLUSH PRIVILEGES;

USE `modelops`;

-- 会话级默认值与生产常用设置
SET NAMES utf8mb4;
SET time_zone = '+08:00';
