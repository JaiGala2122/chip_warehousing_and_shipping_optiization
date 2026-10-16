# Strategic Warehousing and Shipping

Supply chain optimization project to assign orders to eligible warehouses and shipping routes while respecting daily capacity. Built with Excel, Power Query, Python and HiGHS, the project produced a feasible seven-day plan for **9,215 orders**, with a modeled **$141,691.76 reduction in warehouse costs**.

## Project Overview

This project uses historical orders and current network restrictions to examine warehouse dependence, capacity limits and costs.

I started in Excel and Power Query to understand the data and check individual examples. Python then automated the checks across all orders. A mixed-integer linear programming model selected warehouses, shipping routes and processing days.

The main finding was dependence on **PLANT03**: even after considering alternatives, **7,043 orders must use this warehouse**, leaving only **48 spare order slots** over seven days.

## Key Results

- **Optimization Method**: Mixed-Integer Linear Programming (MILP), solved using HiGHS
- **Orders Assigned**: 9,215
- **Planning Horizon**: Seven days
- **Daily Warehouse Capacity Violations**: Zero
- **Historical Assignment Warehouse Cost at Current Rates**: $15,633,221.91
- **New Plan Warehouse Cost**: $15,491,530.16
- **Warehouse-Cost Reduction**: $141,691.76 — approximately 0.9%
- **Plan Freight Cost**: $22,065.48
- **Total Plan Cost**: $15,513,595.64
- **Orders Reassigned to Another Warehouse**: 1,611
- **Remaining Optimization Gap**: 0.0283%
- **Final Solver Time**: 3.66 seconds, excluding data preparation

The solver retained the validated starting plan and established that any further improvement was limited to **$4,394.34 under the model**. Exact optimality was not proved.

## Dataset

- **Source**: [Brunel Supply Chain Logistics Problem Dataset](https://brunel.figshare.com/articles/dataset/Supply_Chain_Logistics_Problem_Dataset/7558679)
- **Size**: 9,215 unique orders across seven related tables
- **Warehouses**: 19
- **Freight Rate Records**: 1,540
- **Decision**: Select an eligible warehouse, shipping route and processing day for each order
- **Objective**: Minimize modeled warehouse and freight costs while satisfying network restrictions

### Tables Used

| Table | Purpose |
|---|---|
| `OrderList` | Historical orders, products, customers, quantities and weights |
| `FreightRates` | Carrier routes, weight bands, rates and minimum charges |
| `PlantPorts` | Allowed warehouse-to-port connections |
| `ProductsPerPlant` | Products supported by each warehouse |
| `VmiCustomers` | Customer restrictions for designated warehouses |
| `WhCapacities` | Maximum orders processed per warehouse per day |
| `WhCosts` | Warehouse cost per product unit |

## Technologies Used

**Tools**: Excel, Power Query, Visual Studio Code

**Programming Language**: Python

**Libraries**:

- Data Analysis: pandas, NumPy
- Excel File Reading: openpyxl
- Optimization and Sparse Matrices: SciPy
- Optimization Solver: HiGHS through highspy

**Analysis and Models Implemented**:

- Historical warehouse allocation and cost analysis
- Automated product, customer and route eligibility checks
- Seven-day warehouse capacity feasibility model
- Minimum PLANT03 dependence model
- Combined warehouse, shipping-route and daily assignment model
- Validation of order coverage, capacity usage and freight costs

## Obstacles and Decisions

- **Large Excel queries**: Freight joins created about a million rows. I retained Excel examples and summaries, then automated the full workflow in Python.
- **Incomplete historical freight coverage**: Some historical routes could not be priced with the current rate card. I compared warehouse costs and reported scenario freight separately.
- **Long solver runtime**: The original formulation ran for over six hours without returning a complete plan. I simplified equivalent pricing calculations, removed unnecessary options and supplied a validated starting schedule.
- **Data and setup errors**: I corrected a missing Power Query column, preserved original order IDs and resolved Python installation and array compatibility issues.

## Assumptions and Limitations

- Seven days is a planning scenario, not a reconstruction of historical shipping dates.
- All orders are available at the start; delivery deadlines and delay penalties are not modeled.
- Orders remain whole, and warehouse capacity counts orders rather than units.
- Warehouse cost equals quantity multiplied by unit cost.
- Compatible orders can share freight pricing groups; customer-arranged freight has zero company freight cost.
- The reported savings cover warehouse costs only. No complete historical freight savings comparison was established.
