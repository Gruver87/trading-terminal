# Очистка API ключей из кода
$file = "C:\Users\vovun\Desktop\github_bot\PROFESSIONAL_TRADING_TERMINAL.py"
$content = Get-Content $file -Raw

# Заменяем реальные ключи на заглушки
$content = $content -replace 'MEXC_API_KEY = "mx0vgl2Uso9d3LN60x"', 'MEXC_API_KEY = "ВАШ_API_KEY_ЗДЕСЬ"'
$content = $content -replace 'MEXC_API_SECRET = "72fd7dba156a40bb8adf6e54709b7bd8"', 'MEXC_API_SECRET = "ВАШ_API_SECRET_ЗДЕСЬ"'
$content = $content -replace 'TELEGRAM_TOKEN = "8763522091:AAFHaXyVXrXqBM8Wyssun9VpgAU6BGttJAI"', 'TELEGRAM_TOKEN = "ВАШ_TELEGRAM_TOKEN"'
$content = $content -replace 'TELEGRAM_CHAT_ID = "1021048982"', 'TELEGRAM_CHAT_ID = "ВАШ_CHAT_ID"'

# Сохраняем
$content | Out-File $file -Encoding UTF8

Write-Host "✅ Ключи очищены!" -ForegroundColor Green
