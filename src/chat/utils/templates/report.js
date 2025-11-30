let i, tab_content, tab_links;
tab_content = document.getElementsByClassName("tab-content");
tab_links = document.getElementsByClassName("tab-link");
if (tab_content.length > 0) tab_content[0].classList.add("active");
if (tab_links.length > 0) tab_links[0].classList.add("active");

// 跟踪哪些tab的图表已经初始化
const initializedTabs = new Set();
// 存储ECharts实例以便销毁和resize
const chartInstances = {};
// 存储初始化函数的引用，以便在showTab中调用
let initializeStaticChartsForPeriod = null;

function showTab(evt, tabName) {
    for (i = 0; i < tab_content.length; i++) {
        tab_content[i].classList.remove("active");
        tab_content[i].style.animation = '';
    }
    for (i = 0; i < tab_links.length; i++) {
        tab_links[i].classList.remove("active");
    }
    document.getElementById(tabName).classList.add("active");
    document.getElementById(tabName).style.animation = 'slideIn 0.5s ease-out';
    evt.currentTarget.classList.add("active");
    
    // 懒加载：只在第一次切换到tab时初始化该tab的图表
    if (!initializedTabs.has(tabName)) {
        if (tabName === 'charts') {
            if (window.initChartsTab) window.initChartsTab();
        } else if (initializeStaticChartsForPeriod) {
            initializeStaticChartsForPeriod(tabName);
        }
        initializedTabs.add(tabName);
    }
    
    // Resize当前tab的图表以确保正确显示
    setTimeout(() => {
        Object.values(chartInstances).forEach(chart => {
            if (chart && chart.resize) chart.resize();
        });
    }, 100);
}

// 窗口resize时调整所有图表
window.addEventListener('resize', function() {
    Object.values(chartInstances).forEach(chart => {
        if (chart && chart.resize) chart.resize();
    });
});

document.addEventListener('DOMContentLoaded', function () {
    // ECharts 通用配色
    const colors = [
        '#2563eb', '#3b82f6', '#60a5fa', '#0891b2', '#06b6d4',
        '#059669', '#10b981', '#7c3aed', '#8b5cf6', '#ec4899',
        '#f97316', '#eab308', '#84cc16', '#14b8a6', '#6366f1'
    ];
    
    // Chart data is injected by python via the HTML template.
    let allChartData = null;
    function getAllChartData() {
        if (!allChartData) {
            try {
                const el = document.getElementById('all_chart_data');
                if (el) allChartData = JSON.parse(el.textContent);
            } catch (e) {
                console.error("Failed to parse all_chart_data:", e);
            }
        }
        return allChartData || {};
    }

    const chartConfigs = {
        totalCost: { id: 'totalCostChart', title: '总花费趋势', yAxisLabel: '花费 (¥)', dataKey: 'total_cost_data' },
        costByModule: { id: 'costByModuleChart', title: '各模块花费对比', yAxisLabel: '花费 (¥)', dataKey: 'cost_by_module' },
        costByModel: { id: 'costByModelChart', title: '各模型花费对比', yAxisLabel: '花费 (¥)', dataKey: 'cost_by_model' },
        messageByChat: { id: 'messageByChatChart', title: '各聊天流消息统计', yAxisLabel: '消息数', dataKey: 'message_by_chat' }
    };

    window.switchTimeRange = function(timeRange) {
        document.querySelectorAll('.time-range-btn').forEach(btn => btn.classList.remove('active'));
        event.target.classList.add('active');
        const data = getAllChartData();
        if (data && data[timeRange]) {
            updateAllCharts(data[timeRange], timeRange);
        }
    }

    function updateAllCharts(data, timeRange) {
        Object.keys(chartConfigs).forEach(type => createChart(type, data, timeRange));
    }

    function createChart(chartType, data, timeRange) {
        const config = chartConfigs[chartType];
        if (!data || !data[config.dataKey]) return;
        
        const container = document.getElementById(config.id);
        if (!container) return;
        
        // 销毁已存在的实例
        if (chartInstances[config.id]) {
            chartInstances[config.id].dispose();
        }
        
        const chart = echarts.init(container);
        chartInstances[config.id] = chart;
        
        let series = [];
        let legendData = [];
        
        if (chartType === 'totalCost') {
            series = [{
                name: config.title,
                type: 'line',
                data: data[config.dataKey],
                smooth: 0.4,
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: 'rgba(37, 99, 235, 0.3)' },
                        { offset: 1, color: 'rgba(37, 99, 235, 0.05)' }
                    ])
                },
                lineStyle: { width: 2, color: '#2563eb' },
                itemStyle: { color: '#2563eb' },
                showSymbol: false,
                emphasis: { focus: 'series' }
            }];
        } else {
            let i = 0;
            Object.entries(data[config.dataKey]).forEach(([name, chartData]) => {
                legendData.push(name);
                series.push({
                    name: name,
                    type: 'line',
                    data: chartData,
                    smooth: 0.4,
                    lineStyle: { width: 2, color: colors[i % colors.length] },
                    itemStyle: { color: colors[i % colors.length] },
                    showSymbol: false,
                    emphasis: { focus: 'series' }
                });
                i++;
            });
        }
        
        // 动态计算图例和布局
        const hasLegend = chartType !== 'totalCost';
        const legendItemCount = legendData.length;
        const needsScrollLegend = legendItemCount > 5;
        
        const option = {
            title: {
                text: config.title,
                left: 'left',
                textStyle: {
                    fontSize: 16,
                    fontWeight: 600,
                    fontFamily: "'Inter', sans-serif",
                    color: '#0f172a'
                }
            },
            tooltip: {
                trigger: 'axis',
                backgroundColor: '#ffffff',
                borderColor: '#e2e8f0',
                borderWidth: 1,
                padding: 12,
                textStyle: { color: '#475569', fontSize: 12 },
                axisPointer: { type: 'cross', crossStyle: { color: '#999' } },
                confine: true // 防止tooltip溢出容器
            },
            legend: {
                show: hasLegend,
                data: legendData,
                type: 'scroll',
                orient: needsScrollLegend ? 'vertical' : 'horizontal',
                right: needsScrollLegend ? 10 : 'center',
                top: needsScrollLegend ? 50 : 35,
                left: needsScrollLegend ? 'auto' : 'center',
                width: needsScrollLegend ? '20%' : 'auto',
                icon: 'circle',
                itemWidth: 8,
                itemHeight: 8,
                textStyle: { 
                    fontSize: 11,
                    width: needsScrollLegend ? 80 : 'auto',
                    overflow: 'truncate',
                    ellipsis: '...'
                },
                pageButtonItemGap: 5,
                pageButtonGap: 5,
                pageIconColor: '#2563eb',
                pageIconInactiveColor: '#aaa',
                pageTextStyle: { fontSize: 10 },
                formatter: function(name) {
                    return name.length > 15 ? name.substring(0, 15) + '...' : name;
                },
                tooltip: { show: true } // 鼠标悬停显示完整名称
            },
            grid: {
                left: '3%',
                right: needsScrollLegend && hasLegend ? '22%' : '4%',
                bottom: '12%',
                top: chartType === 'totalCost' ? 60 : (needsScrollLegend ? 60 : 80),
                containLabel: true
            },
            dataZoom: [
                {
                    type: 'inside',
                    xAxisIndex: 0,
                    filterMode: 'none',
                    zoomOnMouseWheel: 'shift', // 按shift滚轮缩放
                    moveOnMouseMove: true
                },
                {
                    type: 'slider',
                    xAxisIndex: 0,
                    height: 20,
                    bottom: 5,
                    handleSize: '100%',
                    showDetail: false,
                    brushSelect: false
                }
            ],
            xAxis: {
                type: 'category',
                data: data.time_labels,
                boundaryGap: false,
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: '#94a3b8', fontSize: 11 },
                splitLine: { show: false }
            },
            yAxis: {
                type: 'value',
                name: config.yAxisLabel,
                nameTextStyle: { color: '#94a3b8', fontSize: 11 },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: '#94a3b8', fontSize: 11 },
                splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } }
            },
            series: series,
            animation: true,
            animationDuration: 800,
            animationEasing: 'cubicOut'
        };
        
        chart.setOption(option);
    }

    // Function to initialize charts tab
    window.initChartsTab = function() {
        const data = getAllChartData();
        if (data['24h']) {
            updateAllCharts(data['24h'], '24h');
            document.querySelectorAll('.time-range-btn').forEach(btn => {
                if (btn.textContent.includes('24小时')) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });
        }
    };

    // Static charts
    let staticChartData = null;
    function getStaticChartData() {
        if (!staticChartData) {
            try {
                const el = document.getElementById('static_chart_data');
                if (el) staticChartData = JSON.parse(el.textContent);
            } catch (e) {
                console.error("Failed to parse static_chart_data:", e);
            }
        }
        return staticChartData || {};
    }

    // ECharts 扩展调色板
    const extendedColors = [
        '#1976D2', '#42A5F5', '#2196F3', '#64B5F6', '#90CAF9',
        '#00BCD4', '#26C6DA', '#4DD0E1', '#009688', '#26A69A',
        '#4CAF50', '#66BB6A', '#81C784', '#FF9800', '#FFA726',
        '#FF5722', '#FF7043', '#9C27B0', '#AB47BC', '#E91E63',
        '#EC407A', '#607D8B', '#78909C'
    ];

    // 懒加载函数：只初始化指定tab的静态图表
    initializeStaticChartsForPeriod = function(period_id) {
        const data = getStaticChartData();
        if (!data[period_id]) {
            console.warn(`No static chart data for period: ${period_id}`);
            return;
        }
        
        const providerCostData = data[period_id].provider_cost_data;
        const moduleCostData = data[period_id].module_cost_data;
        const modelCostData = data[period_id].model_cost_data;

        // 1. Provider Cost Pie Chart
        const providerContainer = document.getElementById(`providerCostPieChart_${period_id}`);
        if (providerContainer && providerCostData && providerCostData.data && providerCostData.data.length > 0) {
            if (chartInstances[`providerCostPieChart_${period_id}`]) {
                chartInstances[`providerCostPieChart_${period_id}`].dispose();
            }
            const chart = echarts.init(providerContainer);
            chartInstances[`providerCostPieChart_${period_id}`] = chart;
            
            const pieData = providerCostData.labels.map((label, idx) => ({
                name: label,
                value: providerCostData.data[idx]
            }));
            
            const itemCount = pieData.length;
            const useBottomLegend = itemCount > 8;
            
            chart.setOption({
                tooltip: {
                    trigger: 'item',
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    borderRadius: 8,
                    textStyle: { color: '#fff' },
                    confine: true,
                    formatter: function(params) {
                        return `${params.name}<br/>花费: ${params.value.toFixed(4)} ¥<br/>占比: ${params.percent.toFixed(2)}%`;
                    }
                },
                legend: {
                    type: 'scroll',
                    orient: useBottomLegend ? 'horizontal' : 'vertical',
                    right: useBottomLegend ? 'center' : 10,
                    top: useBottomLegend ? 'auto' : 'middle',
                    bottom: useBottomLegend ? 10 : 'auto',
                    left: useBottomLegend ? 'center' : 'auto',
                    width: useBottomLegend ? '90%' : '30%',
                    height: useBottomLegend ? 'auto' : '80%',
                    icon: 'circle',
                    itemWidth: 8,
                    itemHeight: 8,
                    itemGap: useBottomLegend ? 12 : 8,
                    textStyle: { 
                        fontSize: 10,
                        width: useBottomLegend ? 70 : 80,
                        overflow: 'truncate',
                        ellipsis: '...'
                    },
                    pageButtonItemGap: 5,
                    pageButtonGap: 5,
                    pageIconColor: '#2563eb',
                    pageIconInactiveColor: '#aaa',
                    pageTextStyle: { fontSize: 10 },
                    tooltip: { show: true }
                },
                series: [{
                    type: 'pie',
                    radius: ['35%', '60%'],
                    center: useBottomLegend ? ['50%', '40%'] : ['35%', '50%'],
                    avoidLabelOverlap: true,
                    itemStyle: {
                        borderColor: '#fff',
                        borderWidth: 2,
                        borderRadius: 4
                    },
                    label: { show: false },
                    emphasis: {
                        label: { show: true, fontSize: 12, fontWeight: 'bold' },
                        itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' }
                    },
                    data: pieData,
                    color: extendedColors
                }],
                animation: true,
                animationDuration: 1000
            });
        }

        // 2. Module Cost Pie Chart
        const moduleContainer = document.getElementById(`moduleCostPieChart_${period_id}`);
        if (moduleContainer && moduleCostData && moduleCostData.data && moduleCostData.data.length > 0) {
            if (chartInstances[`moduleCostPieChart_${period_id}`]) {
                chartInstances[`moduleCostPieChart_${period_id}`].dispose();
            }
            const chart = echarts.init(moduleContainer);
            chartInstances[`moduleCostPieChart_${period_id}`] = chart;
            
            const pieData = moduleCostData.labels.map((label, idx) => ({
                name: label,
                value: moduleCostData.data[idx]
            }));
            
            const itemCount = pieData.length;
            const useBottomLegend = itemCount > 8;
            
            chart.setOption({
                tooltip: {
                    trigger: 'item',
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    borderRadius: 8,
                    textStyle: { color: '#fff' },
                    confine: true,
                    formatter: function(params) {
                        return `${params.name}<br/>花费: ${params.value.toFixed(4)} ¥<br/>占比: ${params.percent.toFixed(2)}%`;
                    }
                },
                legend: {
                    type: 'scroll',
                    orient: useBottomLegend ? 'horizontal' : 'vertical',
                    right: useBottomLegend ? 'center' : 10,
                    top: useBottomLegend ? 'auto' : 'middle',
                    bottom: useBottomLegend ? 10 : 'auto',
                    left: useBottomLegend ? 'center' : 'auto',
                    width: useBottomLegend ? '90%' : '30%',
                    height: useBottomLegend ? 'auto' : '80%',
                    icon: 'circle',
                    itemWidth: 8,
                    itemHeight: 8,
                    itemGap: useBottomLegend ? 12 : 8,
                    textStyle: { 
                        fontSize: 10,
                        width: useBottomLegend ? 70 : 80,
                        overflow: 'truncate',
                        ellipsis: '...'
                    },
                    pageButtonItemGap: 5,
                    pageButtonGap: 5,
                    pageIconColor: '#2563eb',
                    pageIconInactiveColor: '#aaa',
                    pageTextStyle: { fontSize: 10 },
                    tooltip: { show: true }
                },
                series: [{
                    type: 'pie',
                    radius: ['35%', '60%'],
                    center: useBottomLegend ? ['50%', '40%'] : ['35%', '50%'],
                    avoidLabelOverlap: true,
                    itemStyle: {
                        borderColor: '#fff',
                        borderWidth: 2,
                        borderRadius: 4
                    },
                    label: { show: false },
                    emphasis: {
                        label: { show: true, fontSize: 12, fontWeight: 'bold' },
                        itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' }
                    },
                    data: pieData,
                    color: extendedColors
                }],
                animation: true,
                animationDuration: 1000
            });
        }

        // 3. Model Cost Bar Chart
        const modelContainer = document.getElementById(`modelCostBarChart_${period_id}`);
        if (modelContainer && modelCostData && modelCostData.data && modelCostData.data.length > 0) {
            if (chartInstances[`modelCostBarChart_${period_id}`]) {
                chartInstances[`modelCostBarChart_${period_id}`].dispose();
            }
            
            // 动态调整高度，限制最大高度并使用滚动
            const itemCount = modelCostData.labels.length;
            const needsZoom = itemCount > 15;
            const minHeight = needsZoom ? 450 : Math.max(350, itemCount * 25);
            modelContainer.style.height = minHeight + 'px';
            
            const chart = echarts.init(modelContainer);
            chartInstances[`modelCostBarChart_${period_id}`] = chart;
            
            // 计算显示范围（如果数据太多只显示前15个，其余通过滚动查看）
            const displayEnd = needsZoom ? Math.min(100, Math.round(15 / itemCount * 100)) : 100;
            
            chart.setOption({
                tooltip: {
                    trigger: 'axis',
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    borderRadius: 8,
                    textStyle: { color: '#fff' },
                    axisPointer: { type: 'shadow' },
                    confine: true,
                    formatter: function(params) {
                        if (params[0]) {
                            return `${params[0].name}<br/>花费: ${params[0].value.toFixed(4)} ¥`;
                        }
                        return '';
                    }
                },
                grid: {
                    left: '3%',
                    right: needsZoom ? '8%' : '4%',
                    bottom: '3%',
                    top: 30,
                    containLabel: true
                },
                dataZoom: needsZoom ? [
                    {
                        type: 'slider',
                        yAxisIndex: 0,
                        right: 5,
                        width: 20,
                        start: 0,
                        end: displayEnd,
                        handleSize: '100%',
                        showDetail: false,
                        brushSelect: false
                    },
                    {
                        type: 'inside',
                        yAxisIndex: 0,
                        zoomOnMouseWheel: false,
                        moveOnMouseMove: true,
                        moveOnMouseWheel: true
                    }
                ] : [],
                xAxis: {
                    type: 'value',
                    name: '💰 花费 (¥)',
                    nameTextStyle: { fontSize: 11, fontWeight: 'bold' },
                    axisLabel: { fontSize: 10 },
                    splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.05)' } }
                },
                yAxis: {
                    type: 'category',
                    data: modelCostData.labels,
                    axisLabel: {
                        fontSize: 9,
                        formatter: function(value) {
                            return value.length > 25 ? value.substring(0, 25) + '...' : value;
                        }
                    },
                    axisTick: { show: false },
                    axisLine: { show: false }
                },
                series: [{
                    type: 'bar',
                    data: modelCostData.data.map((value, idx) => ({
                        value: value,
                        itemStyle: { 
                            color: extendedColors[idx % extendedColors.length],
                            borderRadius: [0, 6, 6, 0]
                        }
                    })),
                    barMaxWidth: 20,
                    emphasis: {
                        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.3)' }
                    }
                }],
                animation: true,
                animationDuration: 1000,
                // 大数据优化
                large: true,
                largeThreshold: 100
            });
        }

        // === 新增图表 ===
        
        // 4. Token使用对比条形图
        const tokenCompData = data[period_id].token_comparison_data;
        const tokenCompContainer = document.getElementById(`tokenComparisonChart_${period_id}`);
        if (tokenCompContainer && tokenCompData && tokenCompData.labels && tokenCompData.labels.length > 0) {
            if (chartInstances[`tokenComparisonChart_${period_id}`]) {
                chartInstances[`tokenComparisonChart_${period_id}`].dispose();
            }
            
            const itemCount = tokenCompData.labels.length;
            const needsZoom = itemCount > 10;
            const minHeight = needsZoom ? 400 : Math.max(350, itemCount * 30);
            tokenCompContainer.style.height = minHeight + 'px';
            
            const chart = echarts.init(tokenCompContainer);
            chartInstances[`tokenComparisonChart_${period_id}`] = chart;
            
            chart.setOption({
                tooltip: {
                    trigger: 'axis',
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    borderRadius: 8,
                    textStyle: { color: '#fff' },
                    axisPointer: { type: 'shadow' },
                    confine: true,
                    formatter: function(params) {
                        let result = params[0].name + '<br/>';
                        params.forEach(p => {
                            const total = tokenCompData.input_tokens.reduce((a, b) => a + b, 0) + 
                                         tokenCompData.output_tokens.reduce((a, b) => a + b, 0);
                            const pct = total > 0 ? ((p.value / total) * 100).toFixed(1) : '0.0';
                            result += `${p.marker} ${p.seriesName}: ${p.value.toLocaleString()} tokens (${pct}%)<br/>`;
                        });
                        return result;
                    }
                },
                legend: {
                    data: ['输入Token', '输出Token'],
                    top: 10,
                    icon: 'circle',
                    itemWidth: 10,
                    itemHeight: 10
                },
                grid: {
                    left: '3%',
                    right: '4%',
                    bottom: needsZoom ? '15%' : '3%',
                    top: 50,
                    containLabel: true
                },
                dataZoom: needsZoom ? [
                    {
                        type: 'slider',
                        xAxisIndex: 0,
                        height: 20,
                        bottom: 5,
                        start: 0,
                        end: Math.min(100, Math.round(10 / itemCount * 100)),
                        handleSize: '100%',
                        showDetail: false,
                        brushSelect: false
                    },
                    {
                        type: 'inside',
                        xAxisIndex: 0,
                        zoomOnMouseWheel: 'shift',
                        moveOnMouseMove: true
                    }
                ] : [],
                xAxis: {
                    type: 'category',
                    data: tokenCompData.labels.map(l => l.length > 20 ? l.substring(0, 20) + '...' : l),
                    axisLabel: { 
                        fontSize: 9, 
                        rotate: itemCount > 6 ? 30 : 0,
                        interval: 0
                    },
                    axisTick: { show: false }
                },
                yAxis: {
                    type: 'value',
                    name: 'Token数量',
                    nameTextStyle: { fontSize: 11, fontWeight: 'bold' },
                    axisLabel: { fontSize: 10 },
                    splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.05)' } }
                },
                series: [
                    {
                        name: '输入Token',
                        type: 'bar',
                        data: tokenCompData.input_tokens,
                        itemStyle: { color: '#FF9800', borderRadius: [6, 6, 0, 0] },
                        barMaxWidth: 25
                    },
                    {
                        name: '输出Token',
                        type: 'bar',
                        data: tokenCompData.output_tokens,
                        itemStyle: { color: '#4CAF50', borderRadius: [6, 6, 0, 0] },
                        barMaxWidth: 25
                    }
                ],
                animation: true,
                animationDuration: 1000,
                large: true,
                largeThreshold: 100
            });
        }

        // 5. 供应商请求占比环形图
        const providerReqData = data[period_id].provider_requests_data;
        const providerReqContainer = document.getElementById(`providerRequestsDoughnutChart_${period_id}`);
        if (providerReqContainer && providerReqData && providerReqData.data && providerReqData.data.length > 0) {
            if (chartInstances[`providerRequestsDoughnutChart_${period_id}`]) {
                chartInstances[`providerRequestsDoughnutChart_${period_id}`].dispose();
            }
            const chart = echarts.init(providerReqContainer);
            chartInstances[`providerRequestsDoughnutChart_${period_id}`] = chart;
            
            const pieData = providerReqData.labels.map((label, idx) => ({
                name: label,
                value: providerReqData.data[idx]
            }));
            
            const itemCount = pieData.length;
            const useBottomLegend = itemCount > 8;
            const reqColors = ['#9C27B0', '#E91E63', '#F44336', '#FF9800', '#FFC107', '#FFEB3B', '#CDDC39', '#8BC34A', '#4CAF50', '#009688'];
            
            chart.setOption({
                tooltip: {
                    trigger: 'item',
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    borderRadius: 8,
                    textStyle: { color: '#fff' },
                    confine: true,
                    formatter: function(params) {
                        return `${params.name}<br/>请求数: ${params.value} 次<br/>占比: ${params.percent.toFixed(2)}%`;
                    }
                },
                legend: {
                    type: 'scroll',
                    orient: useBottomLegend ? 'horizontal' : 'vertical',
                    right: useBottomLegend ? 'center' : 10,
                    top: useBottomLegend ? 'auto' : 'middle',
                    bottom: useBottomLegend ? 10 : 'auto',
                    left: useBottomLegend ? 'center' : 'auto',
                    width: useBottomLegend ? '90%' : '30%',
                    height: useBottomLegend ? 'auto' : '80%',
                    icon: 'circle',
                    itemWidth: 8,
                    itemHeight: 8,
                    itemGap: useBottomLegend ? 12 : 8,
                    textStyle: { 
                        fontSize: 10,
                        width: useBottomLegend ? 70 : 80,
                        overflow: 'truncate',
                        ellipsis: '...'
                    },
                    pageButtonItemGap: 5,
                    pageButtonGap: 5,
                    pageIconColor: '#9C27B0',
                    pageIconInactiveColor: '#aaa',
                    pageTextStyle: { fontSize: 10 },
                    tooltip: { show: true }
                },
                series: [{
                    type: 'pie',
                    radius: ['35%', '60%'],
                    center: useBottomLegend ? ['50%', '40%'] : ['35%', '50%'],
                    avoidLabelOverlap: true,
                    itemStyle: {
                        borderColor: '#fff',
                        borderWidth: 2,
                        borderRadius: 4
                    },
                    label: { show: false },
                    emphasis: {
                        label: { show: true, fontSize: 12, fontWeight: 'bold' },
                        itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' }
                    },
                    data: pieData,
                    color: reqColors
                }],
                animation: true,
                animationDuration: 1000
            });
        }

        // 6. 平均响应时间条形图 (横向)
        const avgRespTimeData = data[period_id].avg_response_time_data;
        const avgRespTimeContainer = document.getElementById(`avgResponseTimeChart_${period_id}`);
        if (avgRespTimeContainer && avgRespTimeData && avgRespTimeData.data && avgRespTimeData.data.length > 0) {
            if (chartInstances[`avgResponseTimeChart_${period_id}`]) {
                chartInstances[`avgResponseTimeChart_${period_id}`].dispose();
            }
            
            const itemCount = avgRespTimeData.labels.length;
            const needsZoom = itemCount > 12;
            const minHeight = needsZoom ? 400 : Math.max(350, itemCount * 28);
            avgRespTimeContainer.style.height = minHeight + 'px';
            
            const chart = echarts.init(avgRespTimeContainer);
            chartInstances[`avgResponseTimeChart_${period_id}`] = chart;
            
            const barColors = ['#E91E63', '#9C27B0', '#673AB7', '#3F51B5', '#2196F3', '#00BCD4', '#009688', '#4CAF50'];
            const displayEnd = needsZoom ? Math.min(100, Math.round(12 / itemCount * 100)) : 100;
            
            chart.setOption({
                tooltip: {
                    trigger: 'axis',
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    borderRadius: 8,
                    textStyle: { color: '#fff' },
                    axisPointer: { type: 'shadow' },
                    confine: true,
                    formatter: function(params) {
                        if (params[0]) {
                            return `${params[0].name}<br/>响应时间: ${params[0].value.toFixed(3)} 秒`;
                        }
                        return '';
                    }
                },
                grid: {
                    left: '3%',
                    right: needsZoom ? '8%' : '4%',
                    bottom: '3%',
                    top: 30,
                    containLabel: true
                },
                dataZoom: needsZoom ? [
                    {
                        type: 'slider',
                        yAxisIndex: 0,
                        right: 5,
                        width: 20,
                        start: 0,
                        end: displayEnd,
                        handleSize: '100%',
                        showDetail: false,
                        brushSelect: false
                    },
                    {
                        type: 'inside',
                        yAxisIndex: 0,
                        zoomOnMouseWheel: false,
                        moveOnMouseMove: true,
                        moveOnMouseWheel: true
                    }
                ] : [],
                xAxis: {
                    type: 'value',
                    name: '时间 (秒)',
                    nameTextStyle: { fontSize: 11, fontWeight: 'bold' },
                    axisLabel: { fontSize: 10 },
                    splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.05)' } }
                },
                yAxis: {
                    type: 'category',
                    data: avgRespTimeData.labels.map(l => l.length > 22 ? l.substring(0, 22) + '...' : l),
                    axisLabel: { fontSize: 9 },
                    axisTick: { show: false },
                    axisLine: { show: false }
                },
                series: [{
                    type: 'bar',
                    data: avgRespTimeData.data.map((value, idx) => ({
                        value: value,
                        itemStyle: { 
                            color: barColors[idx % barColors.length],
                            borderRadius: [0, 6, 6, 0]
                        }
                    })),
                    barMaxWidth: 18,
                    emphasis: {
                        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.3)' }
                    }
                }],
                animation: true,
                animationDuration: 1000,
                large: true,
                largeThreshold: 100
            });
        }

        // 7. 模型效率雷达图
        const radarData = data[period_id].model_efficiency_radar_data;
        const radarContainer = document.getElementById(`modelEfficiencyRadarChart_${period_id}`);
        if (radarContainer && radarData && radarData.datasets && radarData.datasets.length > 0) {
            if (chartInstances[`modelEfficiencyRadarChart_${period_id}`]) {
                chartInstances[`modelEfficiencyRadarChart_${period_id}`].dispose();
            }
            const chart = echarts.init(radarContainer);
            chartInstances[`modelEfficiencyRadarChart_${period_id}`] = chart;
            
            const radarColors = ['#00BCD4', '#4CAF50', '#FF9800', '#E91E63', '#9C27B0', '#673AB7', '#2196F3', '#FF5722'];
            
            // 限制显示的模型数量，避免图表过于拥挤
            const maxModels = 5;
            const limitedDatasets = radarData.datasets.slice(0, maxModels);
            
            const indicator = radarData.labels.map(label => ({
                name: label.length > 12 ? label.substring(0, 12) + '...' : label,
                max: 100
            }));
            
            const seriesData = limitedDatasets.map((dataset, idx) => ({
                name: dataset.model.length > 18 ? dataset.model.substring(0, 18) + '...' : dataset.model,
                value: dataset.metrics,
                lineStyle: { color: radarColors[idx % radarColors.length], width: 2 },
                areaStyle: { color: radarColors[idx % radarColors.length] + '30' },
                itemStyle: { color: radarColors[idx % radarColors.length] }
            }));
            
            const legendCount = seriesData.length;
            const useSideLegend = legendCount > 3;
            
            chart.setOption({
                tooltip: {
                    trigger: 'item',
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    borderRadius: 8,
                    textStyle: { color: '#fff' },
                    confine: true
                },
                legend: {
                    data: seriesData.map(s => s.name),
                    type: 'scroll',
                    orient: useSideLegend ? 'vertical' : 'horizontal',
                    right: useSideLegend ? 10 : 'center',
                    top: useSideLegend ? 'middle' : 10,
                    bottom: useSideLegend ? 'auto' : 'auto',
                    width: useSideLegend ? '20%' : 'auto',
                    icon: 'circle',
                    itemWidth: 8,
                    itemHeight: 8,
                    textStyle: { 
                        fontSize: 10,
                        width: useSideLegend ? 70 : 'auto',
                        overflow: 'truncate'
                    },
                    pageButtonItemGap: 5,
                    pageIconColor: '#00BCD4',
                    pageTextStyle: { fontSize: 9 },
                    tooltip: { show: true }
                },
                radar: {
                    indicator: indicator,
                    center: useSideLegend ? ['40%', '50%'] : ['50%', '55%'],
                    radius: useSideLegend ? '65%' : '55%',
                    nameGap: 6,
                    name: {
                        textStyle: { fontSize: 9, fontWeight: 'bold' }
                    },
                    splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.1)' } },
                    splitArea: { show: false },
                    axisLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.1)' } }
                },
                series: [{
                    type: 'radar',
                    data: seriesData,
                    emphasis: {
                        lineStyle: { width: 3 }
                    }
                }],
                animation: true,
                animationDuration: 1200
            });
        }

        // 8. 响应时间分布散点图 (大数据优化)
        const scatterData = data[period_id].response_time_scatter_data;
        const scatterContainer = document.getElementById(`responseTimeScatterChart_${period_id}`);
        if (scatterContainer && scatterData && scatterData.length > 0) {
            if (chartInstances[`responseTimeScatterChart_${period_id}`]) {
                chartInstances[`responseTimeScatterChart_${period_id}`].dispose();
            }
            const chart = echarts.init(scatterContainer);
            chartInstances[`responseTimeScatterChart_${period_id}`] = chart;
            
            // 按模型分组数据，使用数据采样优化性能
            const groupedData = {};
            const maxPointsPerModel = 150; // 每个模型最多150个点
            scatterData.forEach(point => {
                if (!groupedData[point.model]) {
                    groupedData[point.model] = [];
                }
                if (groupedData[point.model].length < maxPointsPerModel) {
                    groupedData[point.model].push([point.x, point.y]);
                }
            });
            
            const scatterColors = ['#4CAF50', '#2196F3', '#FF9800', '#E91E63', '#9C27B0', '#00BCD4', '#FFC107', '#607D8B'];
            const models = Object.keys(groupedData).slice(0, 6); // 限制最多6个模型
            const modelCount = models.length;
            const useSideLegend = modelCount > 4;
            
            const series = models.map((model, idx) => ({
                name: model.length > 18 ? model.substring(0, 18) + '...' : model,
                type: 'scatter',
                data: groupedData[model],
                symbolSize: 5,
                itemStyle: {
                    color: scatterColors[idx % scatterColors.length],
                    opacity: 0.7
                },
                emphasis: {
                    itemStyle: { opacity: 1, shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.3)' }
                },
                // 大数据优化
                large: true,
                largeThreshold: 100
            }));
            
            chart.setOption({
                tooltip: {
                    trigger: 'item',
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    borderRadius: 8,
                    textStyle: { color: '#fff' },
                    confine: true,
                    formatter: function(params) {
                        return `${params.seriesName}<br/>请求 #${params.data[0]}<br/>响应时间: ${params.data[1].toFixed(3)} 秒`;
                    }
                },
                legend: {
                    data: series.map(s => s.name),
                    type: 'scroll',
                    orient: useSideLegend ? 'vertical' : 'horizontal',
                    right: useSideLegend ? 10 : 'center',
                    top: useSideLegend ? 50 : 10,
                    width: useSideLegend ? '18%' : 'auto',
                    icon: 'circle',
                    itemWidth: 8,
                    itemHeight: 8,
                    textStyle: { 
                        fontSize: 10,
                        width: useSideLegend ? 65 : 'auto',
                        overflow: 'truncate'
                    },
                    pageButtonItemGap: 5,
                    pageIconColor: '#4CAF50',
                    pageTextStyle: { fontSize: 9 },
                    tooltip: { show: true }
                },
                grid: {
                    left: '3%',
                    right: useSideLegend ? '22%' : '4%',
                    bottom: '15%',
                    top: useSideLegend ? 50 : 50,
                    containLabel: true
                },
                xAxis: {
                    type: 'value',
                    name: '请求序号',
                    nameTextStyle: { fontSize: 11, fontWeight: 'bold' },
                    axisLabel: { fontSize: 10 },
                    splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.05)' } }
                },
                yAxis: {
                    type: 'value',
                    name: '响应时间 (秒)',
                    nameTextStyle: { fontSize: 11, fontWeight: 'bold' },
                    axisLabel: { fontSize: 10 },
                    splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.05)' } }
                },
                series: series,
                animation: true,
                animationDuration: 1000,
                // 数据缩放支持 - 内置缩放
                dataZoom: [
                    {
                        type: 'inside',
                        xAxisIndex: 0,
                        filterMode: 'empty'
                    },
                    {
                        type: 'inside',
                        yAxisIndex: 0,
                        filterMode: 'empty'
                    },
                    {
                        type: 'slider',
                        xAxisIndex: 0,
                        height: 20,
                        bottom: 5,
                        handleSize: '100%',
                        showDetail: false
                    }
                ]
            });
        }
    };
    
    // 初始化第一个tab(默认显示的tab)的图表
    const firstTab = tab_content[0]?.id;
    if (firstTab && firstTab !== 'charts') {
        initializeStaticChartsForPeriod(firstTab);
        initializedTabs.add(firstTab);
    }
});
