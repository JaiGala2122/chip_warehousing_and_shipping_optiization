from pathlib import Path
import pandas as pd

# Load all seven original tables.
file_path = Path(__file__).parent / "Supply chain logisitcs problem.xlsx"
tables = pd.read_excel(file_path, sheet_name=None)

# Remove extra spaces from column names.
for name, table in tables.items():
    table.columns = table.columns.str.strip()
    print(f"{name}: {len(table):,} rows")

# Compare historical warehouse counts with our Excel summary.
orders = tables["OrderList"]

historical_summary = (
    orders.groupby("Plant Code")["Order ID"]
    .nunique()
    .sort_values(ascending=False)
)

print("\nHistorical orders by warehouse:")
print(historical_summary)
print(f"\nUnique orders: {orders['Order ID'].nunique():,}")

# Find every warehouse that supports each order's product.
products = tables["ProductsPerPlant"].rename(
    columns={"Plant Code": "Eligible Warehouse"}
).drop_duplicates()

options = orders.rename(
    columns={"Plant Code": "Historical Plant"}
).merge(products, on="Product ID", how="left")

# Listed VMI warehouses can serve only their listed customers.
vmi = tables["VmiCustomers"].rename(
    columns={
        "Plant Code": "Eligible Warehouse",
        "Customers": "Customer"
    }
).drop_duplicates()

restricted_plants = vmi["Eligible Warehouse"].unique()
vmi["Customer Match"] = True

options = options.merge(
    vmi,
    on=["Eligible Warehouse", "Customer"],
    how="left",
    validate="many_to_one"
)

allowed = (
    options["Eligible Warehouse"].notna()
    & (
        ~options["Eligible Warehouse"].isin(restricted_plants)
        | options["Customer Match"].eq(True)
    )
)

eligible = options.loc[allowed].drop(columns="Customer Match").copy()

# Validate against the example we checked in Excel.
example = eligible[
    (eligible["Product ID"] == 1689547)
    & (eligible["Historical Plant"] == "PLANT03")
]

print("\nExample: eligible orders by warehouse")
print(example.groupby("Eligible Warehouse")["Order ID"].nunique())

alternatives = example[
    example["Eligible Warehouse"] != example["Historical Plant"]
]["Order ID"].nunique()

print(f"\nExample orders with an alternative: {alternatives}")

# Freight validation for the same 387-unit order used in Excel.
# Excel displays its ID rounded; preserve the original decimal ID.
TEST_ORDER_ID = 1447212844.7

test = eligible[
    eligible["Order ID"] == TEST_ORDER_ID
].copy()

if test.empty:
    raise ValueError("The example order was not found.")

costs = tables["WhCosts"].rename(columns={
    "WH": "Eligible Warehouse",
    "Cost/unit": "Warehouse Cost per Unit"
})

ports = tables["PlantPorts"].rename(columns={
    "Plant Code": "Eligible Warehouse",
    "Port": "Candidate Port"
})

rates = tables["FreightRates"].copy()

# Preserve the source row so overlapping rate entries remain traceable.
rates["Rate Row"] = rates.index + 2
rates = rates.rename(columns={"Carrier": "Candidate Carrier"})

for column in [
    "Candidate Carrier", "orig_port_cd", "dest_port_cd",
    "svc_cd", "mode_dsc"
]:
    rates[column] = rates[column].str.strip()

# Add warehouse costs and permitted origin ports.
test = test.merge(
    costs, on="Eligible Warehouse", how="left",
    validate="many_to_one"
)

test["Warehouse Cost"] = (
    test["Unit quantity"] * test["Warehouse Cost per Unit"]
)

# Check the warehouse costs against the Excel worked example.
expected = {"PLANT02": 184.7938618, "PLANT03": 200.2732321}

for plant, amount in expected.items():
    actual = test.loc[
        test["Eligible Warehouse"] == plant, "Warehouse Cost"
    ]
    assert len(actual) == 1 and abs(actual.iloc[0] - amount) < 0.01, (
        f"Warehouse cost does not match Excel for {plant}"
    )

test = test.merge(ports, on="Eligible Warehouse", how="left")

# Match current routes by port, destination, and service level.
quotes = test.merge(
    rates,
    left_on=["Candidate Port", "Destination Port", "Service Level"],
    right_on=["orig_port_cd", "dest_port_cd", "svc_cd"],
    how="inner"
)

# Scenario assumption: no other orders share this shipment.
quotes["Lane Weight"] = quotes["Weight"]

quotes = quotes[
    quotes["Lane Weight"].between(
        quotes["minm_wgh_qty"], quotes["max_wgh_qty"]
    )
].copy()

if quotes.empty:
    raise ValueError("No matching freight band for this scenario.")

if not quotes["mode_dsc"].isin(["AIR", "GROUND"]).all():
    raise ValueError("An unsupported transportation mode was found.")

# AIR: order weight × rate, subject to minimum charge.
quotes["Freight Cost"] = (
    quotes["Weight"] * quotes["rate"]
).clip(lower=quotes["minimum cost"])

# GROUND: the order's weight share × full-truck rate.
ground = quotes["mode_dsc"].eq("GROUND")
quotes.loc[ground, "Freight Cost"] = (
    quotes.loc[ground, "Weight"]
    / quotes.loc[ground, "Lane Weight"]
    * quotes.loc[ground, "rate"]
)

quotes["Total Cost"] = quotes["Warehouse Cost"] + quotes["Freight Cost"]

columns = [
    "Eligible Warehouse", "Candidate Port", "Candidate Carrier",
    "mode_dsc", "tpt_day_cnt", "Rate Row",
    "Warehouse Cost", "Freight Cost", "Total Cost"
]

print("\nWarehouse costs match Excel.")
print("\nSingle-order shipping scenario — all matching rate entries:")
print(
    quotes.sort_values("Total Cost")[columns]
    .round(2)
    .to_string(index=False)
)

# Check whether the historically used route can be priced here.
historical = quotes[
    quotes["Eligible Warehouse"].eq(quotes["Historical Plant"])
    & quotes["Candidate Port"].eq(quotes["Origin Port"])
    & quotes["Candidate Carrier"].eq(quotes["Carrier"])
    & quotes["tpt_day_cnt"].eq(quotes["TPT"])
]

if historical.empty:
    print("\nHistorical route has no matching rate in this scenario.")
    print("Historical total-cost savings cannot be calculated.")
else:
    print("\nHistorical-route matches at current rates:")
    print(historical[columns].round(2).to_string(index=False))

# Group orders that used the same route and service.
# These are candidate groups, not confirmed shared shipments.

shipping_groups = (
    orders[orders["Service Level"] != "CRF"]
    .groupby([
        "Order Date",
        "Origin Port",
        "Destination Port",
        "Carrier",
        "Service Level",
        "TPT"
    ])
    .agg(
        Orders=("Order ID", "nunique"),
        Combined_Weight=("Weight", "sum")
    )
    .reset_index()
    .sort_values("Orders", ascending=False)
)

print("\nPossible shipping groups:")
print(shipping_groups.head(10).round(2).to_string(index=False))

# One row per order and eligible warehouse.
warehouse_options = eligible[
    ["Order ID", "Eligible Warehouse"]
].drop_duplicates()

# Count warehouse choices for every order.
choice_counts = warehouse_options.groupby(
    "Order ID"
)["Eligible Warehouse"].nunique()

# Identify orders with an alternative to their historical warehouse.
alternative_orders = eligible.loc[
    eligible["Eligible Warehouse"] != eligible["Historical Plant"],
    "Order ID"
].unique()

# Create one summary record per original order.
order_flexibility = orders[
    ["Order ID", "Plant Code"]
].rename(columns={"Plant Code": "Historical Warehouse"}).copy()

order_flexibility["Warehouse Choices"] = (
    order_flexibility["Order ID"]
    .map(choice_counts)
    .fillna(0)
    .astype(int)
)

order_flexibility["Alternative Available"] = (
    order_flexibility["Order ID"].isin(alternative_orders)
)

order_flexibility["Historical Warehouse Only"] = (
    order_flexibility["Warehouse Choices"].eq(1)
    & ~order_flexibility["Alternative Available"]
)

order_flexibility["No Eligible Warehouse"] = (
    order_flexibility["Warehouse Choices"].eq(0)
)

# Summarize all historical warehouses automatically.
flexibility_summary = (
    order_flexibility.groupby("Historical Warehouse")
    .agg(
        Historical_Orders=("Order ID", "nunique"),
        Other_Warehouse_Available=("Alternative Available", "sum"),
        Historical_Warehouse_Only=("Historical Warehouse Only", "sum"),
        No_Eligible_Warehouse=("No Eligible Warehouse", "sum")
    )
    .sort_values("Historical_Orders", ascending=False)
)

print("\nWAREHOUSE FLEXIBILITY — PRODUCT AND CUSTOMER RULES")
print(flexibility_summary.to_string())

# Connect eligible warehouses to their allowed ports.
ports = tables["PlantPorts"].rename(columns={
    "Plant Code": "Eligible Warehouse",
    "Port": "Candidate Port"
}).drop_duplicates()

freight = tables["FreightRates"].copy()

for column in freight.select_dtypes(include="object"):
    freight[column] = freight[column].str.strip()

# Identify routes without selecting a price band yet.
lane_columns = [
    "orig_port_cd", "dest_port_cd", "Carrier",
    "svc_cd", "mode_dsc", "tpt_day_cnt"
]

lanes = (
    freight.groupby(lane_columns, as_index=False)
    .agg(Max_Lane_Weight=("max_wgh_qty", "max"))
    .rename(columns={
        "orig_port_cd": "Candidate Port",
        "dest_port_cd": "Destination Port",
        "Carrier": "Candidate Carrier",
        "svc_cd": "Service Level",
        "mode_dsc": "Mode",
        "tpt_day_cnt": "Transit Days"
    })
)

columns = [
    "Order ID", "Eligible Warehouse", "Destination Port",
    "Service Level", "Weight", "Unit quantity"
]

port_options = (
    eligible[columns]
    .drop_duplicates()
    .merge(ports, on="Eligible Warehouse", how="inner")
)

# Company-arranged shipping must match an available route.
paid_routes = port_options[
    port_options["Service Level"] != "CRF"
].merge(
    lanes,
    on=["Candidate Port", "Destination Port", "Service Level"],
    how="inner"
)

# An unsplit order cannot exceed a route's largest weight limit.
# This does NOT select its price band.
paid_routes = paid_routes[
    paid_routes["Weight"] <= paid_routes["Max_Lane_Weight"]
].copy()

# CRF orders have customer-arranged shipping.
crf_routes = port_options[
    port_options["Service Level"] == "CRF"
].copy()

crf_routes["Candidate Carrier"] = "CUSTOMER_ARRANGED"
crf_routes["Mode"] = "CUSTOMER_ARRANGED"
crf_routes["Transit Days"] = float("nan")
crf_routes["Max_Lane_Weight"] = float("nan")

candidate_routes = pd.concat(
    [paid_routes, crf_routes], ignore_index=True
)

covered = candidate_routes["Order ID"].nunique()
uncovered = orders["Order ID"].nunique() - covered

print("\nSHIPPING ROUTE CHECK")
print(f"Candidate route options: {len(candidate_routes):,}")
print(f"Orders with a candidate route: {covered:,}")
print(f"Orders without a candidate route: {uncovered:,}")

import math

# Count each order once per candidate warehouse.
pairs = candidate_routes[
    ["Order ID", "Eligible Warehouse"]
].drop_duplicates()

choices = pairs.groupby("Order ID")["Eligible Warehouse"].nunique()

# Orders with only one candidate warehouse.
forced_orders = pairs[
    pairs["Order ID"].map(choices).eq(1)
]

forced_counts = forced_orders.groupby(
    "Eligible Warehouse"
)["Order ID"].nunique()

# Compare unavoidable workload with daily processing capacity.
capacity_check = tables["WhCapacities"].rename(columns={
    "Plant ID": "Warehouse"
}).copy()

capacity_check["Orders With No Alternative"] = (
    capacity_check["Warehouse"]
    .map(forced_counts)
    .fillna(0)
    .astype(int)
)

capacity_check["Minimum Processing Days"] = (
    capacity_check["Orders With No Alternative"]
    / capacity_check["Daily Capacity"]
).apply(math.ceil)

capacity_check = capacity_check.sort_values(
    "Orders With No Alternative", ascending=False
)

print("\nUNAVOIDABLE WAREHOUSE WORKLOAD")
print(capacity_check.to_string(index=False))

# Also check total network capacity.
total_daily_capacity = capacity_check["Daily Capacity"].sum()
network_minimum = math.ceil(
    orders["Order ID"].nunique() / total_daily_capacity
)

minimum_days = max(
    network_minimum,
    capacity_check["Minimum Processing Days"].max()
)

print(f"\nTotal daily capacity: {total_daily_capacity:,} orders")
print(f"Minimum processing days implied by these checks: {minimum_days}")

import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix

# Planning scenario: seven days of warehouse processing capacity.
HORIZON_DAYS = 7

# Each possible order–warehouse assignment becomes a yes/no decision.
pairs = candidate_routes[
    ["Order ID", "Eligible Warehouse"]
].drop_duplicates().reset_index(drop=True)

capacity = tables["WhCapacities"].rename(
    columns={"Plant ID": "Warehouse"}
).copy()

order_ids = pd.Index(orders["Order ID"].unique())
plants = pd.Index(capacity["Warehouse"])

order_index = order_ids.get_indexer(pairs["Order ID"])
plant_index = plants.get_indexer(pairs["Eligible Warehouse"])

if (order_index < 0).any() or (plant_index < 0).any():
    raise ValueError("An order or warehouse could not be matched.")

number_orders = len(order_ids)
number_choices = len(pairs)
choice_index = np.arange(number_choices)

# Each choice counts toward:
# 1. Its order's assignment requirement.
# 2. Its warehouse's capacity.
matrix = coo_matrix(
    (
        np.ones(2 * number_choices),
        (
            np.concatenate([
                order_index,
                number_orders + plant_index
            ]),
            np.concatenate([choice_index, choice_index])
        )
    ),
    shape=(number_orders + len(plants), number_choices)
).tocsc()

# Every order must be assigned exactly once.
# Each warehouse must stay within its seven-day capacity.
lower_limits = np.concatenate([
    np.ones(number_orders),
    np.zeros(len(plants))
])

upper_limits = np.concatenate([
    np.ones(number_orders),
    capacity["Daily Capacity"].to_numpy() * HORIZON_DAYS
])

result = milp(
    c=np.zeros(number_choices),  # Find a feasible assignment; no costs yet.
    integrality=np.ones(number_choices),
    bounds=Bounds(0, 1),
    constraints=LinearConstraint(
        matrix, lower_limits, upper_limits
    ),
    options={"time_limit": 60}
)

print("\nSEVEN-DAY WAREHOUSE CAPACITY CHECK")

if result.success:
    assignment = pairs.loc[result.x > 0.5].copy()

    assigned_counts = assignment.groupby(
        "Eligible Warehouse"
    )["Order ID"].nunique()

    capacity["Assigned Orders"] = (
        capacity["Warehouse"]
        .map(assigned_counts)
        .fillna(0)
        .astype(int)
    )

    capacity["Scenario Capacity"] = (
        capacity["Daily Capacity"] * HORIZON_DAYS
    )

    capacity["Remaining Capacity"] = (
        capacity["Scenario Capacity"] - capacity["Assigned Orders"]
    )

    assert len(assignment) == number_orders
    assert assignment["Order ID"].nunique() == number_orders
    assert capacity["Remaining Capacity"].ge(0).all()

    print(f"Orders assigned: {len(assignment):,}")
    print(
        capacity.sort_values(
            "Assigned Orders", ascending=False
        ).to_string(index=False)
    )

elif result.status == 2:
    print("No assignment satisfies these warehouse capacity limits.")

else:
    print("The solver did not finish the check:", result.message)

# Assign a penalty of 1 for choosing PLANT03, and 0 otherwise.
# Minimizing this objective minimizes orders assigned to PLANT03.
plant03_objective = (
    pairs["Eligible Warehouse"].eq("PLANT03")
    .astype(float)
    .to_numpy()
)

dependency_result = milp(
    c=plant03_objective,
    integrality=np.ones(number_choices),
    bounds=Bounds(0, 1),
    constraints=LinearConstraint(
        matrix, lower_limits, upper_limits
    ),
    options={"time_limit": 60, "mip_rel_gap": 0.0}
)

if dependency_result.success:
    dependency_assignment = pairs.loc[
        dependency_result.x > 0.5
    ].copy()

    plant03_count = dependency_assignment[
        "Eligible Warehouse"
    ].eq("PLANT03").sum()

    print("\nMINIMUM PLANT03 DEPENDENCE — WAREHOUSE CONSTRAINTS")
    print(f"Orders assigned to PLANT03: {plant03_count:,}")
    print(f"Share of all orders: {plant03_count / number_orders:.1%}")
else:
    print("Check not completed:", dependency_result.message)

# Add warehouse costs to every candidate route.
warehouse_prices = tables["WhCosts"].set_index("WH")["Cost/unit"]

shipping_options = candidate_routes.copy()

shipping_options["Warehouse Cost"] = (
    shipping_options["Unit quantity"]
    * shipping_options["Eligible Warehouse"].map(warehouse_prices)
)

if shipping_options["Warehouse Cost"].isna().any():
    raise ValueError("A candidate warehouse is missing its cost.")

# Keep the original freight bands for later selection by the solver.
freight_bands = tables["FreightRates"].copy()

for column in freight_bands.select_dtypes(include="object"):
    freight_bands[column] = freight_bands[column].str.strip()

freight_bands = freight_bands.rename(columns={
    "orig_port_cd": "Candidate Port",
    "dest_port_cd": "Destination Port",
    "Carrier": "Candidate Carrier",
    "svc_cd": "Service Level",
    "mode_dsc": "Mode",
    "tpt_day_cnt": "Transit Days"
})

# Orders can share a pricing group only when these details match.
route_keys = [
    "Candidate Port",
    "Destination Port",
    "Candidate Carrier",
    "Service Level",
    "Mode",
    "Transit Days"
]

# Give each distinct shipping route an ID.
lane_lookup = (
    freight_bands[route_keys]
    .drop_duplicates()
    .reset_index(drop=True)
)

lane_lookup["Lane ID"] = lane_lookup.index

# Connect route options and freight bands through that ID.
shipping_options = shipping_options.merge(
    lane_lookup,
    on=route_keys,
    how="left",
    validate="many_to_one"
)

freight_bands = freight_bands.merge(
    lane_lookup,
    on=route_keys,
    how="left",
    validate="many_to_one"
)

# CRF orders do not require a company-paid freight lane.
company_shipping = shipping_options["Service Level"].ne("CRF")

if shipping_options.loc[company_shipping, "Lane ID"].isna().any():
    raise ValueError("A company-arranged route has no matching lane.")

print("\nSHIPPING COST INPUTS PREPARED")
print(f"Candidate route options: {len(shipping_options):,}")
print(f"Distinct freight lanes: {len(lane_lookup):,}")
print(f"Freight rate records: {len(freight_bands):,}")

print("\nExample freight bands:")
print(
    freight_bands[
        ["Lane ID", "minm_wgh_qty", "max_wgh_qty",
         "minimum cost", "rate", "Mode"]
    ].head(10).to_string(index=False)
)

# ============================================================
# PREPARE FREIGHT BRACKETS FOR OPTIMIZATION
# ============================================================

band_columns = [
    "Lane ID",
    "minm_wgh_qty",
    "max_wgh_qty",
    "minimum cost",
    "rate",
    "Mode",
]

model_bands = (
    freight_bands[band_columns]
    .drop_duplicates()
    .reset_index(drop=True)
)

model_bands["Band ID"] = model_bands.index

# Stop if the file contains a transport mode we have not modeled.
unknown_modes = set(model_bands["Mode"]) - {"AIR", "GROUND"}

if unknown_modes:
    raise ValueError(f"Unrecognized transport modes: {unknown_modes}")

# Ground freight is charged at group level.
# Air freight will be calculated for each order below.
model_bands["Group Freight Cost"] = np.where(
    model_bands["Mode"].eq("GROUND"),
    model_bands["rate"],
    0.0,
)

paid_options = shipping_options.loc[
    shipping_options["Service Level"].ne("CRF")
].copy()

priced_options = paid_options.merge(
    model_bands.drop(columns="Mode"),
    on="Lane ID",
    how="inner",
    validate="many_to_many",
)

# An order cannot fit into a group whose maximum weight
# is smaller than that order itself.
priced_options = priced_options.loc[
    priced_options["Weight"] <= priced_options["max_wgh_qty"]
].copy()

# Air charge per order, conditional on the group selecting
# this particular freight bracket.
priced_options["Air Freight Cost"] = np.where(
    priced_options["Mode"].eq("AIR"),
    np.maximum(
        priced_options["Weight"] * priced_options["rate"],
        priced_options["minimum cost"],
    ),
    0.0,
)

priced_options["Order-level Cost"] = (
    priced_options["Warehouse Cost"]
    + priced_options["Air Freight Cost"]
)

# Customer-arranged freight: warehouse costs still apply.
crf_options = shipping_options.loc[
    shipping_options["Service Level"].eq("CRF")
].copy()

crf_options["Order-level Cost"] = crf_options["Warehouse Cost"]

print("\nFREIGHT BRACKET OPTIONS PREPARED")
print(f"Distinct pricing brackets: {len(model_bands):,}")
print(f"Paid route-and-bracket options: {len(priced_options):,}")
print(f"Customer-arranged route options: {len(crf_options):,}")

# ============================================================
# BUILD DAILY ROUTE CHOICES AND SHARED PRICING GROUPS
# ============================================================

planning_days = pd.DataFrame({
    "Day": range(1, HORIZON_DAYS + 1)
})

# Keep the information needed for each routing decision.
route_columns = [
    "Order ID",
    "Eligible Warehouse",
    "Candidate Port",
    "Destination Port",
    "Candidate Carrier",
    "Service Level",
    "Mode",
    "Transit Days",
    "Lane ID",
    "Weight",
    "Warehouse Cost",
]

route_choices = (
    shipping_options[route_columns]
    .drop_duplicates()
    .reset_index(drop=True)
)

# Each order can be assigned to a route on a planning day.
daily_routes = route_choices.merge(planning_days, how="cross")
daily_routes["Route Decision ID"] = np.arange(len(daily_routes))

# Only lanes available to our orders need pricing groups.
active_lanes = route_choices["Lane ID"].dropna().unique()

daily_groups = (
    lane_lookup.loc[
        lane_lookup["Lane ID"].isin(active_lanes),
        ["Lane ID", "Mode"],
    ]
    .merge(planning_days, how="cross")
    .reset_index(drop=True)
)

daily_groups["Group ID"] = np.arange(len(daily_groups))

# Connect each company-arranged route to its daily group.
# CRF routes have no company freight group.
daily_routes = daily_routes.merge(
    daily_groups[["Lane ID", "Day", "Group ID"]],
    on=["Lane ID", "Day"],
    how="left",
    validate="many_to_one",
)

# Each daily group can choose from its lane's freight brackets.
daily_bands = daily_groups.merge(
    model_bands.drop(columns="Mode"),
    on="Lane ID",
    how="inner",
    validate="many_to_many",
)

daily_bands["Bracket Decision ID"] = np.arange(len(daily_bands))

paid_mask = daily_routes["Service Level"].ne("CRF")

if daily_routes.loc[paid_mask, "Group ID"].isna().any():
    raise ValueError("A company-arranged route is missing its pricing group.")

print("\nDAILY MODEL STRUCTURE")
print(f"Planning days: {HORIZON_DAYS}")
print(f"Order-route-day choices: {len(daily_routes):,}")
print(f"Possible daily shipping groups: {len(daily_groups):,}")
print(f"Group freight-bracket choices: {len(daily_bands):,}")

# ============================================================
# UPDATED SHIPPING SOLVER
# Keep all the earlier analysis above this section.
# ============================================================

import json
import time
from datetime import datetime
import highspy
# Set to 0.0 to request the exact minimum within numerical tolerances.
SHIPPING_GAP_TARGET = 0.01

# Final search limit. Earlier analysis and setup take additional time.
# A validated starting plan is saved before this search begins.
# Set to None for an unlimited final search.
SHIPPING_SEARCH_SECONDS = 300


def collect_shipping_inputs():
    """Reuse the tables and route options already prepared above."""
    routes = route_choices.copy().reset_index(drop=True)
    routes["Route ID"] = routes.index
    routes["Air Lower Bound"] = 0.0
    routes["Air Upper Bound"] = 0.0

    bands = model_bands.copy()

    if not orders["Order ID"].is_unique or orders["Order ID"].isna().any():
        raise ValueError("Expected one row per nonmissing Order ID.")

    if set(routes["Order ID"]) != set(orders["Order ID"]):
        raise ValueError("Some orders have no eligible route.")

    if (routes["Weight"] < 0).any() or routes["Weight"].isna().any():
        raise ValueError("Order weights must be nonnegative and present.")

    for lane, chunk in routes[routes["Mode"].eq("AIR")].groupby("Lane ID"):
        quotes = bands[bands["Lane ID"].eq(lane)]
        weights = chunk["Weight"].to_numpy()[:, None]

        cost = np.maximum(
            weights * quotes["rate"].to_numpy(),
            quotes["minimum cost"].to_numpy(),
        )

        valid = weights <= quotes["max_wgh_qty"].to_numpy()

        routes.loc[chunk.index, "Air Lower Bound"] = np.where(
            valid, cost, np.inf
        ).min(axis=1)

        routes.loc[chunk.index, "Air Upper Bound"] = np.where(
            valid, cost, -np.inf
        ).max(axis=1)

    return dict(
        tables=tables,
        orders=orders.copy(),
        routes=routes,
        bands=bands,
        lookup=lane_lookup.copy(),
        days=HORIZON_DAYS,
        capacity=tables["WhCapacities"].rename(
            columns={"Plant ID": "Warehouse"}
        ).copy(),
    )


def daily_tables(data):
    days = pd.DataFrame({"Day": range(1, data["days"] + 1)})

    if "fixed_days" in data:
        routes = data["routes"].merge(
            data["fixed_days"],
            on="Order ID",
            validate="many_to_one",
        )
    else:
        routes = data["routes"].merge(days, how="cross")

    active_lanes = data["routes"]["Lane ID"].dropna().unique()

    groups = (
        data["lookup"][
            data["lookup"]["Lane ID"].isin(active_lanes)
        ][["Lane ID", "Mode"]]
        .merge(days, how="cross")
        .reset_index(drop=True)
    )

    groups["Group ID"] = groups.index

    routes = routes.merge(
        groups[["Lane ID", "Day", "Group ID"]],
        on=["Lane ID", "Day"],
        how="left",
    )

    bands = groups.merge(
        data["bands"].drop(columns="Mode"),
        on="Lane ID",
    ).reset_index(drop=True)

    return routes, groups, bands


def prune_bands(data):
    """Remove unreachable or always-worse bands."""
    data = dict(data)
    routes = data["routes"].copy()
    bands = data["bands"].copy()

    capacity = data["capacity"].set_index("Warehouse")["Daily Capacity"]
    keep = []

    paid_routes = routes[routes["Service Level"].ne("CRF")]

    for lane, chunk in paid_routes.groupby("Lane ID"):
        unique_total = chunk.drop_duplicates("Order ID")["Weight"].sum()

        warehouse_upper = 0.0

        for plant, plant_orders in chunk.groupby("Eligible Warehouse"):
            warehouse_upper += (
                plant_orders.drop_duplicates("Order ID")["Weight"]
                .nlargest(int(capacity[plant]))
                .sum()
            )

        group_upper = min(unique_total, warehouse_upper)

        possible = bands[
            bands["Lane ID"].eq(lane)
            & bands["minm_wgh_qty"].le(group_upper + 1e-8)
        ].copy()

        ids = list(possible.index)
        dropped = set()

        for i in ids:
            if i in dropped:
                continue

            current = possible.loc[i]

            for j in ids:
                if j == i or j in dropped:
                    continue

                other = possible.loc[j]

                covers = (
                    other["minm_wgh_qty"] <= current["minm_wgh_qty"]
                    and min(other["max_wgh_qty"], group_upper)
                    >= min(current["max_wgh_qty"], group_upper)
                )

                cheaper = (
                    other["rate"] <= current["rate"]
                    and (
                        current["Mode"] == "GROUND"
                        or other["minimum cost"] <= current["minimum cost"]
                    )
                )

                strict = (
                    other["rate"] < current["rate"]
                    or (
                        current["Mode"] == "AIR"
                        and other["minimum cost"] < current["minimum cost"]
                    )
                    or other["minm_wgh_qty"] < current["minm_wgh_qty"]
                    or min(other["max_wgh_qty"], group_upper)
                    > min(current["max_wgh_qty"], group_upper)
                    or j < i
                )

                if covers and cheaper and strict:
                    dropped.add(i)
                    break

        keep.extend(i for i in ids if i not in dropped)

    bands = bands.loc[keep].copy()

    routes = routes[
        routes["Service Level"].eq("CRF")
        | routes["Lane ID"].isin(bands["Lane ID"])
    ].copy()

    for lane, chunk in routes[routes["Mode"].eq("AIR")].groupby("Lane ID"):
        quotes = bands[bands["Lane ID"].eq(lane)]
        weights = chunk["Weight"].to_numpy()[:, None]

        cost = np.maximum(
            weights * quotes["rate"].to_numpy(),
            quotes["minimum cost"].to_numpy(),
        )

        valid = weights <= quotes["max_wgh_qty"].to_numpy()

        routes.loc[chunk.index, "Air Lower Bound"] = np.where(
            valid, cost, np.inf
        ).min(axis=1)

        routes.loc[chunk.index, "Air Upper Bound"] = np.where(
            valid, cost, -np.inf
        ).max(axis=1)

    routes = routes[np.isfinite(routes["Air Lower Bound"])].copy()

    assert set(routes["Order ID"]) == set(data["orders"]["Order ID"])

    data["routes"] = routes.reset_index(drop=True)
    data["bands"] = bands.reset_index(drop=True)

    return data


class Rows:
    def __init__(self):
        self.row = []
        self.col = []
        self.val = []
        self.lb = []
        self.ub = []
        self.n = 0

    def add(self, n, terms, lo=-np.inf, hi=np.inf):
        for row, col, val in terms:
            row = np.asarray(row)
            col = np.asarray(col)

            self.row.append(row + self.n)
            self.col.append(col)
            self.val.append(np.broadcast_to(val, col.shape))

        self.lb.append(np.broadcast_to(lo, (n,)))
        self.ub.append(np.broadcast_to(hi, (n,)))
        self.n += n

    def finish(self, nvars):
        matrix = coo_matrix(
            (
                np.concatenate(self.val),
                (
                    np.concatenate(self.row),
                    np.concatenate(self.col),
                ),
            ),
            shape=(self.n, nvars),
        ).tocsc()

        matrix.eliminate_zeros()

        return matrix, np.concatenate(self.lb), np.concatenate(self.ub)


def build_model(data, strengthened=False, symmetry=False, compact=False):
    routes, groups, bands = daily_tables(data)

    nr = len(routes)
    nb = len(bands)
    ng = len(groups)

    route_var = np.arange(nr)
    band_var = nr + np.arange(nb)
    rate_var = nr + nb + np.arange(ng)
    minimum_var = nr + nb + ng + np.arange(ng)

    # .copy() keeps the array writable under pandas 3.
    air_mask = routes["Mode"].eq("AIR").to_numpy().copy()

    # If the AIR price never changes, put it directly in the objective.
    if compact:
        air_mask &= (
            routes["Air Upper Bound"] - routes["Air Lower Bound"]
        ).to_numpy() > 0.0

    air = np.flatnonzero(air_mask)

    charge_var = nr + nb + 2 * ng + np.arange(len(air))
    variable_count = nr + nb + 2 * ng + len(air)

    paid = np.flatnonzero(
        routes["Service Level"].ne("CRF").to_numpy()
    )

    route_group = routes.iloc[paid]["Group ID"].to_numpy(dtype=int)
    band_group = bands["Group ID"].to_numpy(dtype=int)
    air_group = routes.iloc[air]["Group ID"].to_numpy(dtype=int)

    weights = routes["Weight"].to_numpy()
    group_ids = np.arange(ng)
    air_bands = bands["Mode"].eq("AIR").to_numpy()

    max_rate = (
        bands.assign(v=np.where(air_bands, bands["rate"], 0))
        .groupby("Group ID")["v"]
        .max()
        .reindex(group_ids, fill_value=0)
        .to_numpy()
    )

    max_minimum = (
        bands.assign(v=np.where(air_bands, bands["minimum cost"], 0))
        .groupby("Group ID")["v"]
        .max()
        .reindex(group_ids, fill_value=0)
        .to_numpy()
    )

    rate_limit = weights[air] * max_rate[air_group]
    minimum_limit = max_minimum[air_group]
    charge_limit = np.maximum(rate_limit, minimum_limit)

    base = (
        routes.iloc[air]["Air Lower Bound"].to_numpy()
        if compact
        else np.zeros(len(air))
    )

    objective = np.zeros(variable_count)

    objective[route_var] = routes["Warehouse Cost"] + (
        routes["Air Lower Bound"] if compact else 0
    )

    objective[band_var] = bands["Group Freight Cost"]
    objective[charge_var] = 1

    integrality = np.zeros(variable_count, dtype=np.uint8)
    integrality[:nr + nb] = 1

    if compact:
        charge_limit = routes.iloc[air]["Air Upper Bound"].to_numpy() - base

    upper = np.ones(variable_count)
    upper[rate_var] = max_rate
    upper[minimum_var] = max_minimum
    upper[charge_var] = charge_limit

    rows = Rows()

    order_index = pd.Index(data["orders"]["Order ID"]).get_indexer(
        routes["Order ID"]
    )

    plant_index = pd.Index(data["capacity"]["Warehouse"]).get_indexer(
        routes["Eligible Warehouse"]
    )

    days = data["days"]

    assert (order_index >= 0).all()
    assert (plant_index >= 0).all()

    # Every order is assigned exactly once.
    rows.add(
        len(data["orders"]),
        [(order_index, route_var, 1)],
        1,
        1,
    )

    # Warehouse capacity is enforced separately on every day.
    warehouse_day = plant_index * days + routes["Day"].to_numpy() - 1

    rows.add(
        len(data["capacity"]) * days,
        [(warehouse_day, route_var, 1)],
        hi=np.repeat(
            data["capacity"]["Daily Capacity"].to_numpy(),
            days,
        ),
    )

    # At most one weight band per lane and day.
    rows.add(ng, [(band_group, band_var, 1)], hi=1)

    # Combined group weight must fit its selected band.
    rows.add(
        ng,
        [
            (route_group, route_var[paid], weights[paid]),
            (band_group, band_var, -bands["max_wgh_qty"].to_numpy()),
        ],
        hi=0,
    )

    rows.add(
        ng,
        [
            (route_group, route_var[paid], weights[paid]),
            (band_group, band_var, -bands["minm_wgh_qty"].to_numpy()),
        ],
        lo=0,
    )

    counts = (
        routes.iloc[paid]
        .groupby("Group ID")["Order ID"]
        .nunique()
        .reindex(group_ids, fill_value=0)
        .to_numpy()
    )

    # Used groups select a band; unused groups do not.
    rows.add(
        ng,
        [
            (route_group, route_var[paid], 1),
            (band_group, band_var, -counts[band_group]),
        ],
        hi=0,
    )

    rows.add(
        ng,
        [
            (route_group, route_var[paid], 1),
            (band_group, band_var, -np.ones(nb)),
        ],
        lo=0,
    )

    # Set group AIR prices from the chosen band.
    rows.add(
        ng,
        [
            (group_ids, rate_var, 1),
            (
                band_group,
                band_var,
                -np.where(air_bands, bands["rate"], 0),
            ),
        ],
        0,
        0,
    )

    rows.add(
        ng,
        [
            (group_ids, minimum_var, 1),
            (
                band_group,
                band_var,
                -np.where(air_bands, bands["minimum cost"], 0),
            ),
        ],
        0,
        0,
    )

    # AIR price = max(order weight × group rate, minimum charge).
    air_index = np.arange(len(air))

    rows.add(
        len(air),
        [
            (air_index, charge_var, 1),
            (air_index, rate_var[air_group], -weights[air]),
            (air_index, route_var[air], base - rate_limit),
        ],
        lo=-rate_limit,
    )

    rows.add(
        len(air),
        [
            (air_index, charge_var, 1),
            (air_index, minimum_var[air_group], -np.ones(len(air))),
            (air_index, route_var[air], base - minimum_limit),
        ],
        lo=-minimum_limit,
    )

    rows.add(
        len(air),
        [
            (air_index, charge_var, 1),
            (air_index, route_var[air], -charge_limit),
        ],
        hi=0,
    )

    if strengthened and not compact:
        rows.add(
            len(air),
            [
                (air_index, charge_var, 1),
                (
                    air_index,
                    route_var[air],
                    -routes.iloc[air]["Air Lower Bound"].to_numpy(),
                ),
            ],
            lo=0,
        )

    if symmetry:
        for day in range(1, days):
            first = routes.index[
                routes["Eligible Warehouse"].eq("PLANT03")
                & routes["Day"].eq(day)
            ].to_numpy()

            second = routes.index[
                routes["Eligible Warehouse"].eq("PLANT03")
                & routes["Day"].eq(day + 1)
            ].to_numpy()

            rows.add(
                1,
                [
                    (np.zeros(len(first), dtype=int), first, 1),
                    (np.zeros(len(second), dtype=int), second, -1),
                ],
                lo=0,
            )

    matrix, lower_limits, upper_limits = rows.finish(variable_count)

    return dict(
        c=objective,
        integrality=integrality,
        lb=np.zeros(variable_count),
        ub=upper,
        A=matrix,
        lo=lower_limits,
        hi=upper_limits,
        routes=routes,
        groups=groups,
        bands=bands,
        nr=nr,
        nb=nb,
        rate_var=rate_var,
        minimum_var=minimum_var,
        air_rows=air,
        charge_var=charge_var,
        charge_base=base,
    )


def relaxed_assignment(data):
    """Build the initial assignment and a valid lower cost bound."""
    routes = data["routes"]
    count = len(routes)

    order_index = pd.Index(data["orders"]["Order ID"]).get_indexer(
        routes["Order ID"]
    )

    plant_index = pd.Index(data["capacity"]["Warehouse"]).get_indexer(
        routes["Eligible Warehouse"]
    )

    rows = Rows()

    rows.add(
        len(data["orders"]),
        [(order_index, np.arange(count), 1)],
        1,
        1,
    )

    rows.add(
        len(data["capacity"]),
        [(plant_index, np.arange(count), 1)],
        hi=data["capacity"]["Daily Capacity"].to_numpy() * data["days"],
    )

    matrix, lower, upper = rows.finish(count)

    result = milp(
        (routes["Warehouse Cost"] + routes["Air Lower Bound"]).to_numpy(),
        integrality=np.ones(count),
        bounds=Bounds(0, 1),
        constraints=LinearConstraint(matrix, lower, upper),
        options={"time_limit": 60, "mip_rel_gap": 0},
    )

    if not result.success:
        raise RuntimeError(result.message)

    plan = routes.loc[result.x > 0.5].copy()

    plan = plan.sort_values(
        ["Eligible Warehouse", "Weight", "Order ID"],
        ascending=[True, False, True],
    )

    plan["Day"] = (
        plan.groupby("Eligible Warehouse").cumcount() % data["days"] + 1
    )

    return plan, float(result.mip_dual_bound)


def price_and_validate(data, plan):
    orders = data["orders"]
    bands = data["bands"]
    routes = data["routes"]
    capacity = data["capacity"]

    if (
        len(plan) != len(orders)
        or not plan["Order ID"].is_unique
        or set(plan["Order ID"]) != set(orders["Order ID"])
    ):
        raise ValueError("Order coverage failed.")

    if not plan["Day"].between(1, data["days"]).all():
        raise ValueError("Day outside planning horizon.")

    allowed = set(zip(routes["Order ID"], routes["Route ID"]))

    if not all(
        (order_id, route_id) in allowed
        for order_id, route_id in zip(plan["Order ID"], plan["Route ID"])
    ):
        raise ValueError("Ineligible route.")

    load = (
        plan.groupby(["Eligible Warehouse", "Day"])
        .size()
        .rename("Assigned Orders")
        .reset_index()
        .merge(
            capacity,
            left_on="Eligible Warehouse",
            right_on="Warehouse",
            validate="many_to_one",
        )
    )

    if (load["Assigned Orders"] > load["Daily Capacity"]).any():
        raise ValueError("Daily capacity exceeded.")

    quote_rows = []
    total_air = 0.0
    total_ground = 0.0
    invalid = []

    paid = plan[plan["Service Level"].ne("CRF")]

    for (lane, day), chunk in paid.groupby(["Lane ID", "Day"]):
        weight = chunk["Weight"].sum()

        quotes = bands[
            bands["Lane ID"].eq(lane)
            & bands["minm_wgh_qty"].le(weight + 1e-8)
            & bands["max_wgh_qty"].ge(weight - 1e-8)
        ].copy()

        if quotes.empty:
            invalid.append((int(lane), int(day), float(weight)))
            continue

        if chunk.iloc[0]["Mode"] == "AIR":
            cost = np.maximum(
                chunk["Weight"].to_numpy()[:, None]
                * quotes["rate"].to_numpy(),
                quotes["minimum cost"].to_numpy(),
            ).sum(axis=0)
        else:
            cost = quotes["rate"].to_numpy()

        index = int(np.argmin(cost))
        quote = quotes.iloc[index].to_dict()

        quote.update(
            Day=int(day),
            Combined_Weight=float(weight),
            Orders=len(chunk),
            Freight_Cost=float(cost[index]),
        )

        quote_rows.append(quote)

        if quote["Mode"] == "AIR":
            total_air += cost[index]
        else:
            total_ground += cost[index]

    if invalid:
        raise ValueError("Groups without matching bracket: " + str(invalid))

    warehouse = float(plan["Warehouse Cost"].sum())

    totals = dict(
        orders=len(plan),
        warehouse_cost=warehouse,
        air_cost=float(total_air),
        ground_cost=float(total_ground),
        total_cost=float(warehouse + total_air + total_ground),
        plant03_orders=int(plan["Eligible Warehouse"].eq("PLANT03").sum()),
    )

    return totals, pd.DataFrame(quote_rows), load


def repair_seed(data, plan):
    """Repair the starting plan only; do not restrict the final search."""
    plan = plan.copy().reset_index(drop=True)
    routes = data["routes"]
    bands = data["bands"]

    def group_price(lane, weights):
        total_weight = float(np.sum(weights))

        quotes = bands[
            bands["Lane ID"].eq(lane)
            & bands["minm_wgh_qty"].le(total_weight + 1e-8)
            & bands["max_wgh_qty"].ge(total_weight - 1e-8)
        ]

        if quotes.empty:
            return np.inf

        if quotes.iloc[0]["Mode"] == "GROUND":
            return float(quotes["rate"].min())

        return float(
            np.maximum(
                np.asarray(weights)[:, None] * quotes["rate"].to_numpy(),
                quotes["minimum cost"].to_numpy(),
            ).sum(axis=0).min()
        )

    for iteration in range(100):
        bad = None

        paid = plan[plan["Service Level"].ne("CRF")]

        for (lane, day), chunk in paid.groupby(["Lane ID", "Day"]):
            if not np.isfinite(group_price(lane, chunk["Weight"].to_numpy())):
                bad = (lane, day, chunk)
                break

        if bad is None:
            return plan

        lane, day, chunk = bad
        common = None
        alternatives = []

        for _, order in chunk.iterrows():
            possible = routes[
                routes["Order ID"].eq(order["Order ID"])
                & routes["Eligible Warehouse"].eq(order["Eligible Warehouse"])
            ]

            choices = set(possible["Lane ID"].dropna()) - {lane}

            common = choices if common is None else common & choices
            alternatives.append(possible)

        best = None

        for target in sorted(common or []):
            existing_weights = plan[
                plan["Lane ID"].eq(target) & plan["Day"].eq(day)
            ]["Weight"].to_numpy()

            combined_weights = np.r_[
                existing_weights,
                chunk["Weight"].to_numpy(),
            ]

            cost = group_price(target, combined_weights)

            if not np.isfinite(cost):
                continue

            previous_cost = (
                group_price(target, existing_weights)
                if len(existing_weights)
                else 0
            )

            increase = cost - previous_cost

            if best is None or increase < best[0]:
                best = (increase, target)

        if best is None:
            raise RuntimeError(
                f"Could not repair starting group {(lane, day)}. "
                "This does not prove the full model is infeasible."
            )

        for index, possible in zip(chunk.index, alternatives):
            replacement = possible[
                possible["Lane ID"].eq(best[1])
            ].iloc[0]

            for column in routes.columns:
                plan.at[index, column] = replacement[column]

    raise RuntimeError("Starting-plan repair iteration limit reached.")


def validate_vector(model, solution, tol=1e-5):
    activity = model["A"] @ solution

    error = max(
        0,
        float(np.max(model["lo"] - activity)),
        float(np.max(activity - model["hi"])),
        float(np.max(model["lb"] - solution)),
        float(np.max(solution - model["ub"])),
    )

    integers = solution[model["integrality"] > 0]

    error = max(
        error,
        float(np.max(np.abs(integers - np.rint(integers)))),
    )

    if error > tol:
        raise ValueError(f"Constraint/integrality violation: {error}")

    return error


def make_start(data, model, plan):
    loads = (
        plan[plan["Eligible Warehouse"].eq("PLANT03")]
        .groupby("Day")
        .size()
        .reindex(range(1, data["days"] + 1), fill_value=0)
    )

    if "fixed_days" not in data:
        mapping = {
            day: index + 1
            for index, day in enumerate(
                loads.sort_values(ascending=False, kind="stable").index
            )
        }
    else:
        mapping = {day: day for day in loads.index}

    plan = plan.copy()
    plan["Day"] = plan["Day"].map(mapping)

    totals, quotes, _ = price_and_validate(data, plan)

    routes = model["routes"]
    bands = model["bands"]
    solution = np.zeros(len(model["c"]))

    route_indices = pd.MultiIndex.from_frame(
        routes[["Route ID", "Day"]]
    ).get_indexer(
        pd.MultiIndex.from_frame(plan[["Route ID", "Day"]])
    )

    assert (route_indices >= 0).all()
    solution[route_indices] = 1

    band_indices = pd.MultiIndex.from_frame(
        bands[["Band ID", "Day"]]
    ).get_indexer(
        pd.MultiIndex.from_frame(quotes[["Band ID", "Day"]])
    )

    assert (band_indices >= 0).all()
    solution[model["nr"] + band_indices] = 1

    for index in band_indices:
        quote = bands.iloc[index]
        group = int(quote["Group ID"])

        if quote["Mode"] == "AIR":
            solution[model["rate_var"][group]] = quote["rate"]
            solution[model["minimum_var"][group]] = quote["minimum cost"]

    air = model["air_rows"]
    active = solution[air] > 0.5

    air_group = routes.iloc[air]["Group ID"].to_numpy(dtype=int)

    solution[model["charge_var"]] = np.where(
        active,
        np.maximum(
            routes.iloc[air]["Weight"].to_numpy()
            * solution[model["rate_var"][air_group]],
            solution[model["minimum_var"][air_group]],
        ) - model["charge_base"],
        0,
    )

    validate_vector(model, solution)

    assert abs(model["c"] @ solution - totals["total_cost"]) < 1e-5

    return solution, totals


def highs_model(model):
    problem = highspy.HighsLp()
    matrix = model["A"]

    problem.num_col_ = len(model["c"])
    problem.num_row_ = matrix.shape[0]
    problem.col_cost_ = model["c"]
    problem.col_lower_ = model["lb"]
    problem.col_upper_ = model["ub"]
    problem.row_lower_ = model["lo"]
    problem.row_upper_ = model["hi"]

    problem.integrality_ = [
        highspy.HighsVarType.kInteger
        if integer
        else highspy.HighsVarType.kContinuous
        for integer in model["integrality"]
    ]

    problem.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    problem.a_matrix_.start_ = matrix.indptr
    problem.a_matrix_.index_ = matrix.indices
    problem.a_matrix_.value_ = matrix.data

    return problem


def solve_highs(model, seconds=60, start=None, options=None, log=None):
    solver = highspy.Highs()

    settings = {
        "time_limit": seconds,
        "mip_rel_gap": 0.0,
        "mip_abs_gap": 1e-6,
        "threads": 1,
        "output_flag": True,
        "log_to_console": False,
    }

    if log:
        settings["log_file"] = str(log)

    settings.update(options or {})

    for key, value in settings.items():
        if solver.setOptionValue(key, value) != highspy.HighsStatus.kOk:
            raise ValueError(f"Unsupported HiGHS option: {key}")

    if solver.passModel(highs_model(model)) != highspy.HighsStatus.kOk:
        raise RuntimeError("HiGHS could not load the shipping model.")

    if start is not None:
        starting_solution = highspy.HighsSolution()
        starting_solution.col_value = start
        starting_solution.value_valid = True

        if solver.setSolution(starting_solution) != highspy.HighsStatus.kOk:
            raise RuntimeError("HiGHS could not accept the starting plan.")

    started = time.perf_counter()
    solver.run()
    elapsed = time.perf_counter() - started

    info = solver.getInfo()
    solution = solver.getSolution()
    status = solver.modelStatusToString(solver.getModelStatus())

    if info.primal_solution_status == highspy.SolutionStatus.kSolutionStatusFeasible:
        values = np.asarray(solution.col_value)
    else:
        values = None

    report = dict(
        engine="HiGHS",
        version=solver.version(),
        status=status,
        solve_seconds=elapsed,
        objective=float(info.objective_function_value)
        if values is not None else None,
        dual_bound=float(info.mip_dual_bound),
        gap=float(info.mip_gap),
        nodes=int(info.mip_node_count),
    )

    return report, values


def export_plan(original, plan, destination, label):
    totals, quotes, loads = price_and_validate(original, plan)

    source = original["orders"][
        ["Order ID", "Product ID", "Customer", "Unit quantity", "Plant Code"]
    ].rename(columns={"Plant Code": "Historical Plant"})

    detail = plan.merge(source, on="Order ID", validate="one_to_one")
    detail["Freight Cost"] = 0.0

    for _, quote in quotes.iterrows():
        mask = (
            detail["Lane ID"].eq(quote["Lane ID"])
            & detail["Day"].eq(quote["Day"])
        )

        if quote["Mode"] == "AIR":
            detail.loc[mask, "Freight Cost"] = np.maximum(
                detail.loc[mask, "Weight"] * quote["rate"],
                quote["minimum cost"],
            )
        elif quote["Combined_Weight"] > 0:
            detail.loc[mask, "Freight Cost"] = (
                detail.loc[mask, "Weight"]
                / quote["Combined_Weight"]
                * quote["Freight_Cost"]
            )
        else:
            detail.loc[mask, "Freight Cost"] = (
                quote["Freight_Cost"] / int(mask.sum())
            )

    detail["Total Cost"] = detail["Warehouse Cost"] + detail["Freight Cost"]

    if not np.isclose(
        detail["Total Cost"].sum(),
        totals["total_cost"],
        rtol=0,
        atol=1e-5,
    ):
        raise ValueError("Exported costs do not reconcile.")

    days = pd.DataFrame({"Day": range(1, original["days"] + 1)})

    capacity = original["capacity"][
        ["Warehouse", "Daily Capacity"]
    ].merge(days, how="cross")

    count = (
        detail.groupby(["Eligible Warehouse", "Day"])
        .size()
        .rename("Assigned Orders")
        .reset_index()
    )

    capacity = capacity.merge(
        count,
        left_on=["Warehouse", "Day"],
        right_on=["Eligible Warehouse", "Day"],
        how="left",
    ).drop(columns="Eligible Warehouse")

    capacity["Assigned Orders"] = (
        capacity["Assigned Orders"].fillna(0).astype(int)
    )

    capacity["Remaining Capacity"] = (
        capacity["Daily Capacity"] - capacity["Assigned Orders"]
    )

    destination.mkdir(parents=True, exist_ok=True)

    detail.to_csv(
        destination / f"{label}_orders.csv",
        index=False,
        float_format="%.17g",
    )

    quotes.to_csv(
        destination / f"{label}_freight_groups.csv",
        index=False,
        float_format="%.17g",
    )

    capacity.to_csv(
        destination / f"{label}_daily_capacity.csv",
        index=False,
    )

    (destination / f"{label}_cost.json").write_text(
        json.dumps(totals, indent=2)
    )

    return totals


def run_updated_shipping_solver():
    if SHIPPING_SEARCH_SECONDS is not None and SHIPPING_SEARCH_SECONDS <= 0:
        raise ValueError("Use a positive search time, or None for unlimited.")

    if SHIPPING_GAP_TARGET < 0:
        raise ValueError("The gap target cannot be negative.")

    started = time.perf_counter()

    output = (
        Path(__file__).parent
        / "shipping_results"
        / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )

    output.mkdir(parents=True, exist_ok=True)

    original = collect_shipping_inputs()
    reduced = prune_bands(original)

    print("\nUPDATED SHIPPING SEARCH", flush=True)
    print(f"Orders retained: {len(original['orders']):,}", flush=True)

    print(
        f"Route choices: {len(original['routes']):,}"
        f" -> {len(reduced['routes']):,}",
        flush=True,
    )

    print(
        f"Freight bands: {len(original['bands']):,}"
        f" -> {len(reduced['bands']):,}",
        flush=True,
    )

    print("Building and checking a complete starting plan...", flush=True)

    starting_plan, lower_bound = relaxed_assignment(reduced)
    starting_plan = repair_seed(reduced, starting_plan)

    initial = export_plan(
        original, starting_plan, output, "starting_plan"
    )

    # Save a usable plan before the full search begins.
    export_plan(original, starting_plan, output, "best_plan")

    initial_summary = dict(
        initial,
        status="Starting plan validated; final search not completed",
        global_lower_bound=lower_bound,
        proven_optimal=False,
    )

    (output / "solve_summary.json").write_text(
        json.dumps(initial_summary, indent=2),
        encoding="utf-8",
    )

    print(
        f"Starting plan saved: ${initial['total_cost']:,.2f}",
        flush=True,
    )

    print(f"Results folder: {output.resolve()}", flush=True)

    model = build_model(reduced, compact=True)
    start, _ = make_start(reduced, model, starting_plan)

    print(
        f"Full model: {len(model['c']):,} variables; "
        f"{model['A'].shape[0]:,} constraints",
        flush=True,
    )

    print(
        "All eligible warehouse, route and day choices remain open.",
        flush=True,
    )

    print(
        f"Requested cost gap: {SHIPPING_GAP_TARGET:.2%}",
        flush=True,
    )

    print(
        f"Search limit: "
        f"{SHIPPING_SEARCH_SECONDS if SHIPPING_SEARCH_SECONDS is not None else 'none'}"
        f" seconds",
        flush=True,
    )

    options = {
        "presolve": "off",
        "mip_detect_symmetry": False,
        "mip_heuristic_effort": 0.0,
        "mip_heuristic_run_feasibility_jump": False,
        "mip_heuristic_run_rins": False,
        "mip_heuristic_run_rens": False,
        "mip_heuristic_run_root_reduced_cost": False,
        "mip_rel_gap": SHIPPING_GAP_TARGET,
        "log_to_console": True,
    }

    try:
        report, solution = solve_highs(
            model,
            math.inf
            if SHIPPING_SEARCH_SECONDS is None
            else SHIPPING_SEARCH_SECONDS,
            start,
            options,
            output / "solver.log",
        )
    except KeyboardInterrupt:
        print(
            "\nSearch interrupted. The validated starting plan is already saved.",
            flush=True,
        )
        print(f"Results folder: {output.resolve()}", flush=True)
        return initial_summary, starting_plan
    except Exception:
        print(
            f"\nSearch failed. The validated starting plan remains in "
            f"{output.resolve()}",
            flush=True,
        )
        raise

    best_plan = starting_plan

    if solution is not None:
        validate_vector(model, solution)

        candidate = model["routes"].loc[
            solution[:model["nr"]] > 0.5
        ].copy()

        candidate_cost, _, _ = price_and_validate(original, candidate)

        if candidate_cost["total_cost"] <= initial["total_cost"] + 1e-6:
            best_plan = candidate

    totals = export_plan(original, best_plan, output, "best_plan")

    solver_bound = report.get("dual_bound")

    if solver_bound is not None and np.isfinite(solver_bound):
        lower_bound = max(lower_bound, solver_bound)

    if lower_bound > totals["total_cost"] + 1e-4:
        raise ValueError(
            "Reported lower bound exceeds the validated plan cost; investigate."
        )

    difference = max(0.0, totals["total_cost"] - lower_bound)
    gap = difference / max(abs(totals["total_cost"]), 1e-12)

    report.update(totals)

    report.update(
        global_lower_bound=lower_bound,
        remaining_cost_uncertainty=difference,
        validated_relative_gap=gap,
        requested_gap=SHIPPING_GAP_TARGET,
        requested_seconds=SHIPPING_SEARCH_SECONDS,
        elapsed_seconds=time.perf_counter() - started,
        proven_optimal=(
            report["status"] == "Optimal"
            and difference <= 1e-4
        ),
    )

    report = {
        key: (
            None
            if isinstance(value, float) and not math.isfinite(value)
            else value
        )
        for key, value in report.items()
    }

    (output / "solve_summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    print("\nVALIDATED SHIPPING RESULT")
    print(f"Orders assigned: {totals['orders']:,}")
    print(f"Warehouse cost: ${totals['warehouse_cost']:,.2f}")

    print(
        f"Freight cost: "
        f"${totals['air_cost'] + totals['ground_cost']:,.2f}"
    )

    print(f"Total cost: ${totals['total_cost']:,.2f}")
    print(f"Lower cost bound: ${lower_bound:,.2f}")
    print(f"Remaining gap: {gap:.6%} (up to ${difference:,.2f})")

    if report["proven_optimal"]:
        print("Cheapest cost proved within numerical tolerances.")
    elif gap <= SHIPPING_GAP_TARGET:
        print(
            "Requested cost-gap target met. "
            "Exact cheapest cost is NOT proved."
        )
    else:
        print(
            "Feasible plan saved; requested cost-gap target has not been met."
        )

    print(f"Results folder: {output.resolve()}")

    return report, best_plan


if __name__ == "__main__":
    shipping_result, shipping_plan = run_updated_shipping_solver()