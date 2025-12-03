# 邮件订阅功能使用指南

## 功能概述

邮件订阅功能允许用户订阅特定股票的提醒，当股票发生重要变化时（如价格大幅波动、重要新闻等），系统会自动发送邮件通知。

## 配置邮件服务

### 1. 环境变量配置

在 `.env` 文件中添加以下配置：

```env
# SMTP 服务器配置（以 Gmail 为例）
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password  # Gmail 需要使用应用专用密码
EMAIL_FROM=your_email@gmail.com
```

### 2. Gmail 配置说明

如果使用 Gmail：

1. 启用两步验证
2. 生成应用专用密码：
   - 访问：https://myaccount.google.com/apppasswords
   - 选择"邮件"和"其他（自定义名称）"
   - 生成密码并复制到 `SMTP_PASSWORD`

### 3. 其他邮件服务商配置

- **Outlook/Hotmail**: `smtp-mail.outlook.com:587`
- **QQ邮箱**: `smtp.qq.com:587`
- **163邮箱**: `smtp.163.com:25`

## API 使用

### 订阅股票提醒

```bash
POST /api/subscribe
Content-Type: application/json

{
    "email": "user@example.com",
    "ticker": "AAPL",
    "alert_types": ["price_change", "news"],  # 可选
    "price_threshold": 5.0  # 可选，价格变动阈值（百分比）
}
```

**响应**:
```json
{
    "success": true,
    "message": "已成功订阅 AAPL 的提醒",
    "email": "user@example.com",
    "ticker": "AAPL"
}
```

### 取消订阅

```bash
POST /api/unsubscribe
Content-Type: application/json

{
    "email": "user@example.com",
    "ticker": "AAPL"  # 可选，如果不提供则取消所有订阅
}
```

### 查询订阅列表

```bash
GET /api/subscriptions?email=user@example.com
```

**响应**:
```json
{
    "success": true,
    "subscriptions": [
        {
            "email": "user@example.com",
            "ticker": "AAPL",
            "alert_types": ["price_change", "news"],
            "price_threshold": 5.0,
            "created_at": "2025-11-30T10:00:00",
            "updated_at": "2025-11-30T10:00:00",
            "last_alert_at": null
        }
    ],
    "count": 1
}
```

## 提醒类型

- **price_change**: 价格变动提醒（当价格变动超过阈值时）
- **news**: 重要新闻提醒
- **report**: 分析报告提醒

## 数据存储

订阅数据存储在 `data/subscriptions.json` 文件中，格式如下：

```json
{
    "user@example.com": [
        {
            "email": "user@example.com",
            "ticker": "AAPL",
            "alert_types": ["price_change", "news"],
            "price_threshold": 5.0,
            "created_at": "2025-11-30T10:00:00",
            "updated_at": "2025-11-30T10:00:00",
            "last_alert_at": null
        }
    ]
}
```

## 邮件模板

系统会发送格式化的 HTML 邮件，包含：
- 股票代码和当前价格
- 涨跌幅信息
- 提醒消息
- 发送时间

## 注意事项

1. **邮件服务配置**: 必须正确配置 SMTP 服务器信息才能发送邮件
2. **应用专用密码**: Gmail 需要使用应用专用密码，不能使用普通密码
3. **速率限制**: 注意邮件发送的速率限制，避免被标记为垃圾邮件
4. **数据备份**: 订阅数据存储在本地文件，建议定期备份

## 后续开发

计划添加的功能：
- 定时监控任务（检查价格变动和新闻）
- 更智能的提醒阈值（基于历史波动率）
- 邮件模板自定义
- 批量订阅管理
- 邮件发送队列和重试机制

