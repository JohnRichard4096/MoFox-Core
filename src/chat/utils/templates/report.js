let i, tab_content, tab_links;
tab_content = document.getElementsByClassName("tab-content");
tab_links = document.getElementsByClassName("tab-link");
if (tab_content.length > 0) tab_content[0].classList.add("active");
if (tab_links.length > 0) tab_links[0].classList.add("active");

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
}

document.addEventListener('DOMContentLoaded', function () {
 // Chart data is injected by python via the HTML template.
    let allChartData = {};
    try {
        allChartData = JSON.parse(all_chart_data_json_string);
    } catch (e) {
        console.error("Failed to parse all_chart_data:", e);
        console.error("Problematic all_chart_data string:", all_chart_data_json_string);
    }

    let currentCharts = {};
    const chartConfigs = {
        totalCost: { id: 'totalCostChart', title: '总花费趋势', yAxisLabel: '花费 (¥)', dataKey: 'total_cost_data', fill: true },
        costByModule: { id: 'costByModuleChart', title: '各模块花费对比', yAxisLabel: '花费 (¥)', dataKey: 'cost_by_module', fill: false },
        costByModel: { id: 'costByModelChart', title: '各模型花费对比', yAxisLabel: '花费 (¥)', dataKey: 'cost_by_model', fill: false },
        messageByChat: { id: 'messageByChatChart', title: '各聊天流消息统计', yAxisLabel: '消息数', dataKey: 'message_by_chat', fill: false }
    };

    window.switchTimeRange = function(timeRange) {
        document.querySelectorAll('.time-range-btn').forEach(btn => btn.classList.remove('active'));
        event.target.classList.add('active');
        updateAllCharts(allChartData[timeRange], timeRange);
    }

    function updateAllCharts(data, timeRange) {
        Object.values(currentCharts).forEach(chart => chart && chart.destroy());
        currentCharts = {};
        Object.keys(chartConfigs).forEach(type => createChart(type, data, timeRange));
    }

    function createChart(chartType, data, timeRange) {
        const config = chartConfigs[chartType];
        if (!data || !data[config.dataKey]) return;
        // Material Design 3 Blue/Gray Color Palette
        const colors = ['#1976D2', '#546E7A', '#42A5F5', '#90CAF9', '#78909C', '#B0BEC5', '#1565C0', '#607D8B', '#2196F3', '#CFD8DC'];
        let datasets = [];
        if (chartType === 'totalCost') {
            datasets = [{ 
                label: config.title, 
                data: data[config.dataKey], 
                borderColor: '#1976D2', 
                backgroundColor: 'rgba(25, 118, 210, 0.1)', 
                tension: 0.3, 
                fill: config.fill,
                borderWidth: 2,
                pointRadius: 3,
                pointHoverRadius: 5,
                pointBackgroundColor: '#1976D2',
                pointBorderColor: '#fff',
                pointBorderWidth: 2
            }];
        } else {
            let i = 0;
            Object.entries(data[config.dataKey]).forEach(([name, chartData]) => {
                datasets.push({ 
                    label: name, 
                    data: chartData, 
                    borderColor: colors[i % colors.length], 
                    backgroundColor: colors[i % colors.length] + '30', 
                    tension: 0.4, 
                    fill: config.fill,
                    borderWidth: 2,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    pointBackgroundColor: colors[i % colors.length],
                    pointBorderColor: '#fff',
                    pointBorderWidth: 1
                });
                i++;
            });
        }
        const canvas = document.getElementById(config.id);
        if (!canvas) return;
        
        currentCharts[chartType] = new Chart(canvas, {
            type: 'line',
            data: { labels: data.time_labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2.5,
                plugins: { 
                    title: { 
                        display: true, 
                        text: `${config.title}`, 
                        font: { size: 16, weight: '500' },
                        color: '#1C1B1F',
                        padding: { top: 8, bottom: 16 }
                    }, 
                    legend: { 
                        display: chartType !== 'totalCost', 
                        position: 'top',
                        labels: {
                            usePointStyle: true,
                            padding: 15,
                            font: { size: 12 }
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        padding: 12,
                        titleFont: { size: 14 },
                        bodyFont: { size: 13 },
                        cornerRadius: 8
                    }
                },
                scales: { 
                    x: { 
                        title: { 
                            display: true, 
                            text: '⏰ 时间',
                            font: { size: 13, weight: 'bold' }
                        },
                        ticks: { maxTicksLimit: 12 },
                        grid: { color: 'rgba(0, 0, 0, 0.05)' }
                    }, 
                    y: { 
                        title: { 
                            display: true, 
                            text: config.yAxisLabel,
                            font: { size: 13, weight: 'bold' }
                        },
                        beginAtZero: true,
                        grid: { color: 'rgba(0, 0, 0, 0.05)' }
                    } 
                },
                interaction: { 
                    intersect: false, 
                    mode: 'index' 
                },
                animation: {
                    duration: 1000,
                    easing: 'easeInOutQuart'
                }
            }
        });
    }

    if (allChartData['24h']) {
        updateAllCharts(allChartData['24h'], '24h');
        // Activate the 24h button by default
        document.querySelectorAll('.time-range-btn').forEach(btn => {
            if (btn.textContent.includes('24小时')) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    // Static charts
    let staticChartData = {};
    try {
        staticChartData = JSON.parse(static_chart_data_json_string);
    } catch (e) {
        console.error("Failed to parse static_chart_data:", e);
        console.error("Problematic static_chart_data string:", static_chart_data_json_string);
    }

    Object.keys(staticChartData).forEach(period_id => {
        const providerCostData = staticChartData[period_id].provider_cost_data;
        const modelCostData = staticChartData[period_id].model_cost_data;
        const colors = ['#3498db', '#2ecc71', '#f1c40f', '#e74c3c', '#9b59b6', '#1abc9c', '#34495e', '#e67e22'];

        // Provider Cost Pie Chart
        const providerCtx = document.getElementById(`providerCostPieChart_${period_id}`);
        if (providerCtx && providerCostData && providerCostData.data && providerCostData.data.length > 0) {
            new Chart(providerCtx, {
                type: 'doughnut',
                data: {
                    labels: providerCostData.labels,
                    datasets: [{
                        label: '按供应商花费',
                        data: providerCostData.data,
                        backgroundColor: colors,
                        borderColor: '#FFFFFF',
                        borderWidth: 2,
                        hoverOffset: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    aspectRatio: 1.5,
                    plugins: {
                        title: { 
                            display: true, 
                            text: '按供应商花费分布', 
                            font: { size: 14, weight: '500' },
                            color: '#1C1B1F',
                            padding: { top: 8, bottom: 16 }
                        },
                        legend: { 
                            position: 'right',
                            labels: {
                                usePointStyle: true,
                                padding: 15,
                                font: { size: 12 }
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            padding: 12,
                            titleFont: { size: 14 },
                            bodyFont: { size: 13 },
                            cornerRadius: 8,
                            callbacks: {
                                label: function(context) {
                                    let label = context.label || '';
                                    if (label) {
                                        label += ': ';
                                    }
                                    label += context.parsed.toFixed(4) + ' ¥';
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = ((context.parsed / total) * 100).toFixed(2);
                                    label += ` (${percentage}%)`;
                                    return label;
                                }
                            }
                        }
                    },
                    animation: {
                        animateRotate: true,
                        animateScale: true,
                        duration: 1000,
                        easing: 'easeInOutQuart'
                    }
                }
            });
        }

        // Model Cost Bar Chart
        const modelCtx = document.getElementById(`modelCostBarChart_${period_id}`);
        if (modelCtx && modelCostData && modelCostData.data && modelCostData.data.length > 0) {
            new Chart(modelCtx, {
                type: 'bar',
                data: {
                    labels: modelCostData.labels,
                    datasets: [{
                        label: '按模型花费',
                        data: modelCostData.data,
                        backgroundColor: colors,
                        borderColor: colors,
                        borderWidth: 2,
                        borderRadius: 8,
                        hoverBackgroundColor: colors.map(c => c + 'dd')
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    aspectRatio: 1.5,
                    plugins: {
                        title: { 
                            display: true, 
                            text: '按模型花费排行', 
                            font: { size: 14, weight: '500' },
                            color: '#1C1B1F',
                            padding: { top: 8, bottom: 16 }
                        },
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            padding: 12,
                            titleFont: { size: 14 },
                            bodyFont: { size: 13 },
                            cornerRadius: 8,
                            callbacks: {
                                label: function(context) {
                                    return context.dataset.label + ': ' + context.parsed.y.toFixed(4) + ' ¥';
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { display: false }
                        },
                        y: { 
                            beginAtZero: true, 
                            title: { 
                                display: true, 
                                text: '💰 花费 (¥)',
                                font: { size: 13, weight: 'bold' }
                            },
                            grid: { color: 'rgba(0, 0, 0, 0.05)' }
                        }
                    },
                    animation: {
                        duration: 1000,
                        easing: 'easeInOutQuart'
                    }
                }
            });
        }
    });
});