document.addEventListener("DOMContentLoaded", function () {
    new Chart(document.getElementById("powerChart"), {
        type: "line",
        data: {
            labels: powerData.map(r => r.datetime),
            datasets: [{
                label: "Predicted Power (W)",
                data: powerData.map(r => r.predicted_power_W),
                borderWidth: 2,
                tension: 0.3,
                fill: true
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    labels: { color: "white" } // ✅ legend text
                }
            },
            scales: {
                x: {
                    ticks: { color: "white" }, // ✅ x values
                    title: {
                        display: true,
                        text: "Time",
                        color: "white" // ✅ x-axis title
                    },
                    border: { color: "white" },
                    grid: { color: "rgba(255,255,255,0.3)" }
                },
                y: {
                    ticks: { color: "white" }, // ✅ y values
                    title: {
                        display: true,
                        text: "Power (W)",
                        color: "white" // ✅ y-axis title
                    },
                    border: { color: "white" },
                    grid: { color: "rgba(255,255,255,0.3)" }
                }
            }
        }
    });

    new Chart(document.getElementById("yieldChart"), {
        type: "bar",
        data: {
            labels: dailyData.map(r => r.date),
            datasets: [{
                label: "Energy (Wh)",
                data: dailyData.map(r => r.predicted_daily_yield_Wh),
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    labels: { color: "white" } // ✅ legend text
                }
            },
            scales: {
                x: {
                    ticks: { color: "white" },
                    title: {
                        display: true,
                        text: "Date",
                        color: "white"
                    },
                    border: { color: "white" },
                    grid: { color: "rgba(255,255,255,0.3)" }
                },
                y: {
                    ticks: { color: "white" },
                    title: {
                        display: true,
                        text: "Energy (Wh)",
                        color: "white"
                    },
                    border: { color: "white" },
                    grid: { color: "rgba(255,255,255,0.3)" }
                }
            }
        }
    });

    // ========= Chart 3: Weather Factors vs Daily Yield =========
    new Chart(document.getElementById("weatherChart"), {
        type: "line",
        data: {
            labels: weatherData.map(r => r.date),
            datasets: [
                {
                    label: "Daily Yield (Wh)",
                    data: weatherData.map(r => r.predicted_daily_yield_Wh),
                    borderWidth: 2,
                    tension: 0.3,
                    yAxisID: "yWh"
                },
                {
                    label: "Sun Hours",
                    data: weatherData.map(r => r.sun_hours),
                    borderWidth: 2,
                    tension: 0.3,
                    yAxisID: "yWh"
                },
                {
                    label: "Cloud Coverage (%)",
                    data: weatherData.map(r => r.clouds),
                    borderWidth: 2,
                    tension: 0.3,
                    yAxisID: "yOther"
                },
                {
                    label: "Temperature (°C)",
                    data: weatherData.map(r => r.temp_day),
                    borderWidth: 2,
                    tension: 0.3,
                    yAxisID: "yTemp",
                    borderDash: [4, 4] // optional styling
                }
            ]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    labels: {
                        color: "white" // Legend text
                    }
                }
            },
            scales: {
                x: {
                    ticks: {
                        color: "white"
                    },
                    title: {
                        display: true,
                        text: "Date",
                        color: "white"
                    },
                    border: {
                        color: "white" // ✅ x-axis border line
                    },
                    grid: {
                        color: "rgba(255,255,255,0.3)" // ✅ white grid lines (soft)
                    }
                },
                yWh: {
                    type: "linear",
                    position: "left",
                    title: { 
                        display: true, 
                        text: "Energy Yield (Wh)",
                        color: "white"
                    },
                    ticks: {
                        color: "white"
                    },
                    border: {
                        color: "white" // ✅ left axis border line
                    },
                    grid: {
                        color: "rgba(255,255,255,0.3)"
                    }
                },
                yTemp: {
                    type: "linear",
                    position: "right",
                    title: {
                        display: true,
                        text: "Temperature (°C)",
                        color: "white"
                    },
                    ticks: {
                        color: "white"
                    },
                    grid: { 
                        drawOnChartArea: false 
                    },
                    border: {
                        color: "white" // ✅ right axis border line
                    }
                },
                yOther: {
                    display: false
                }
            }
        }
    });

    // ========= System Time and Data Timestamp =========
    function updateSystemTime() {
    let now = new Date();
    document.getElementById("systemTime").textContent = now.toLocaleString();
    document.getElementById("dataTimestamp").textContent = powerData.length ? powerData[0].datetime : "-";    
    }

    setInterval(updateSystemTime, 1000);  // Keep clock updating
    updateSystemTime();

});