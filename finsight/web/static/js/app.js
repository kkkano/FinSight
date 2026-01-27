/**
 * FinSight 前端应用逻辑
 *
 * 处理用户查询、结果展示、页面导航和系统监控。
 */

// API 基础路径
const API_BASE = '/api/v1';

// 分析历史存储
const history = [];

// ==================== 页面导航 ====================

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        const page = item.dataset.page;

        // 更新导航状态
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        item.classList.add('active');

        // 切换页面
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById(`page-${page}`).classList.add('active');

        // 切换到监控页时自动刷新
        if (page === 'metrics') {
            refreshMetrics();
        }
    });
});

// ==================== 快捷查询 ====================

document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
        document.getElementById('queryInput').value = chip.dataset.query;
        submitQuery();
    });
});

// ==================== 键盘快捷键 ====================

document.getElementById('queryInput').addEventListener('keydown', (e) => {
    // Ctrl+Enter 提交查询
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        submitQuery();
    }
});

// ==================== 核心查询逻辑 ====================

async function submitQuery() {
    const queryInput = document.getElementById('queryInput');
    const query = queryInput.value.trim();

    if (!query) {
        showError('请输入查询内容', '查询内容不能为空，请输入金融分析问题。');
        return;
    }

    const mode = document.querySelector('input[name="mode"]:checked').value;

    // 切换按钮状态
    setLoading(true);
    hideError();
    hideResult();

    try {
        const response = await fetch(`${API_BASE}/analyze`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ query, mode }),
        });

        const data = await response.json();

        if (!response.ok) {
            const errorMsg = data.error_message || data.detail || '请求失败';
            showError('分析失败', errorMsg);
            return;
        }

        // 展示结果
        showResult(data, query, mode);

        // 保存到历史
        addToHistory(query, mode, data);

    } catch (error) {
        console.error('请求错误:', error);
        showError('网络错误', '无法连接到 FinSight API 服务，请检查后端是否已启动。');
    } finally {
        setLoading(false);
    }
}

// ==================== 结果展示 ====================

function showResult(data, query, mode) {
    const area = document.getElementById('resultArea');
    const content = document.getElementById('resultContent');
    const title = document.getElementById('resultTitle');
    const intentBadge = document.getElementById('resultIntent');
    const modeBadge = document.getElementById('resultMode');
    const timeBadge = document.getElementById('resultTime');
    const dataArea = document.getElementById('resultData');
    const dataPre = document.getElementById('resultDataPre');

    // 设置标题
    title.textContent = truncate(query, 50);

    // 设置意图标签
    const intentMap = {
        stock_price: '股价查询',
        stock_news: '股票新闻',
        analyze_stock: '股票分析',
        market_sentiment: '市场情绪',
        compare_assets: '资产对比',
        macro_events: '经济日历',
        greeting: '问候',
        clarify: '待澄清',
    };
    intentBadge.textContent = intentMap[data.intent] || data.intent || '分析';

    // 设置模式标签
    modeBadge.textContent = mode === 'deep' ? '深度分析' : '摘要分析';

    // 设置耗时
    if (data.latency_ms) {
        timeBadge.textContent = `${Math.round(data.latency_ms)}ms`;
    } else {
        timeBadge.textContent = '';
    }

    // 设置内容
    content.textContent = data.report || data.message || '无分析内容';

    // 设置原始数据（如果有）
    if (data.data && Object.keys(data.data).length > 0) {
        dataPre.textContent = JSON.stringify(data.data, null, 2);
        dataArea.style.display = 'block';
    } else {
        dataArea.style.display = 'none';
    }

    area.style.display = 'block';
}

function hideResult() {
    document.getElementById('resultArea').style.display = 'none';
}

// ==================== 错误处理 ====================

function showError(title, message) {
    document.getElementById('errorTitle').textContent = title;
    document.getElementById('errorMessage').textContent = message;
    document.getElementById('errorArea').style.display = 'block';
}

function hideError() {
    document.getElementById('errorArea').style.display = 'none';
}

function clearError() {
    hideError();
}

// ==================== 加载状态 ====================

function setLoading(loading) {
    const btn = document.getElementById('analyzeBtn');
    const btnText = btn.querySelector('.btn-text');
    const btnLoading = btn.querySelector('.btn-loading');

    btn.disabled = loading;
    btnText.style.display = loading ? 'none' : 'inline';
    btnLoading.style.display = loading ? 'flex' : 'none';
}

// ==================== 分析历史 ====================

function addToHistory(query, mode, data) {
    const item = {
        query,
        mode,
        report: data.report || data.message || '',
        intent: data.intent,
        timestamp: new Date().toLocaleString('zh-CN'),
    };

    history.unshift(item);

    // 最多保留 50 条
    if (history.length > 50) {
        history.pop();
    }

    renderHistory();
}

function renderHistory() {
    const list = document.getElementById('historyList');

    if (history.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📭</span>
                <p>暂无分析记录</p>
            </div>
        `;
        return;
    }

    list.innerHTML = history.map((item, index) => `
        <div class="history-item" onclick="loadHistoryItem(${index})">
            <div class="history-item-header">
                <span class="history-item-query">${escapeHtml(truncate(item.query, 40))}</span>
                <span class="history-item-time">${item.timestamp}</span>
            </div>
            <div class="history-item-preview">${escapeHtml(truncate(item.report, 100))}</div>
        </div>
    `).join('');
}

function loadHistoryItem(index) {
    const item = history[index];
    if (!item) return;

    // 切换到分析页面
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelector('[data-page="analyze"]').classList.add('active');
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-analyze').classList.add('active');

    // 填充数据
    document.getElementById('queryInput').value = item.query;

    // 展示历史结果
    showResult({
        report: item.report,
        intent: item.intent,
    }, item.query, item.mode);
}

// ==================== 系统监控 ====================

async function refreshMetrics() {
    try {
        const response = await fetch(`${API_BASE}/metrics/all`);
        if (!response.ok) throw new Error('获取指标失败');

        const data = await response.json();

        // 更新 API 状态
        document.getElementById('metricApiStatus').textContent = '正常运行';
        document.getElementById('metricApiStatus').style.color = 'var(--success)';

        // 更新缓存命中率
        if (data.cache) {
            const caches = Object.values(data.cache);
            if (caches.length > 0) {
                const totalHits = caches.reduce((s, c) => s + (c.hits || 0), 0);
                const totalMisses = caches.reduce((s, c) => s + (c.misses || 0), 0);
                const total = totalHits + totalMisses;
                const hitRate = total > 0 ? (totalHits / total * 100).toFixed(1) : '0';
                document.getElementById('metricCacheHit').textContent = `${hitRate}%`;
            }
        }

        // 更新限流状态
        if (data.rate_limits) {
            const limiters = Object.values(data.rate_limits);
            const totalRejected = limiters.reduce((s, l) => s + (l.rejected || 0), 0);
            document.getElementById('metricRateLimit').textContent =
                totalRejected > 0 ? `${totalRejected} 次拒绝` : '正常';
            document.getElementById('metricRateLimit').style.color =
                totalRejected > 0 ? 'var(--warning)' : 'var(--success)';
        }

        // 更新成本
        if (data.costs) {
            const totalCost = data.costs.total_cost || 0;
            document.getElementById('metricCost').textContent = `$${totalCost.toFixed(4)}`;
        }

    } catch (error) {
        console.error('获取指标失败:', error);
        document.getElementById('metricApiStatus').textContent = '连接失败';
        document.getElementById('metricApiStatus').style.color = 'var(--danger)';
    }
}

// ==================== API 健康检查 ====================

async function checkApiHealth() {
    const statusEl = document.getElementById('apiStatus');
    const dot = statusEl.querySelector('.status-dot');
    const text = statusEl.querySelector('span:last-child');

    try {
        const response = await fetch(`${API_BASE}/health`);
        if (response.ok) {
            dot.className = 'status-dot online';
            text.textContent = 'API 在线';
        } else {
            dot.className = 'status-dot offline';
            text.textContent = 'API 异常';
        }
    } catch {
        dot.className = 'status-dot offline';
        text.textContent = 'API 离线';
    }
}

// ==================== 工具函数 ====================

function truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.substring(0, maxLen) + '...' : str;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ==================== 初始化 ====================

// 页面加载时检查 API 状态
checkApiHealth();

// 每 30 秒检查一次
setInterval(checkApiHealth, 30000);
