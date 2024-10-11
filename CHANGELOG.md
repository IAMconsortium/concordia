# Emissions

## 2024-10-11

### REMIND-MAgPIE
- MAgPIE
  - Bugfix in LUC emissions reducing spikes from soil organic matter loss
- REMIND
  - Change transport policy assumptions in sensitivity runs, assuming a more
    gradual change between very low (cp3000) and very high (cp0400) ambition
    scenarios. Scenarios with original assumptions are still being reported
    for comparison (and as fall-back option) and are marked with the suffix
    `-T_Mix4`, which represents the transport policy mix that is shared by
    all these scenarios.

## 2024-08-19

- gridded dataset for 2015-2100 in 10-year steps for 8 scenarios:
  - RESCUE-Tier1-Direct-2024-08-19-PkBudg500-OAE_off
  - RESCUE-Tier1-Direct-2024-08-19-PkBudg1150-OAE_off
  - RESCUE-Tier1-Direct-2024-08-19-PkBudg500-OAE_on
  - RESCUE-Tier1-Direct-2024-08-19-PkBudg1150-OAE_on
  - RESCUE-Tier1-Direct-2024-08-19-EocBudg500-OAE_off
  - RESCUE-Tier1-Direct-2024-08-19-EocBudg1150-OAE_off
  - RESCUE-Tier1-Direct-2024-08-19-EocBudg500-OAE_on
  - RESCUE-Tier1-Direct-2024-08-19-EocBudg1150-OAE_on

- harmonized data for 2020-2100 in 5-year steps until 2060 and 10-year steps until 2100 for 30 scenarios (8 direct scenarios above and 22 additional sensitivity runs):

  - RESCUE-Tier1-Sensitivity-2024-08-19-Baseline
  - RESCUE-Tier1-Sensitivity-2024-08-19-NPi
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0400-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0450-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0500-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0600-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0750-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp1000-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp1300-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp1700-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp2300-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp3000-OAE_off
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0400-OAE_on
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0450-OAE_on
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0500-OAE_on
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0600-OAE_on
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp0750-OAE_on
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp1000-OAE_on
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp1300-OAE_on
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp1700-OAE_on
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp2300-OAE_on
  - RESCUE-Tier1-Sensitivity-2024-08-19-EocBudg_cp3000-OAE_on

### Gridding
- Grids all cdr sectors in CO2_em_anthro with simple patterns:
  - `CDR Afforestation`,
  - `CDR BECCS`,
  - `CDR DACCS`,
  - `CDR EW` (no data in Tier 1 scenarios),
  - `CDR Industry`,
  - `CDR OAE Uptake Ocean`

- Adds two new sectors to the `CO2_em_anthro` variable (for anthropogenic CO2 emissions):
  - The sector `Deforestation and LUC` are the positive emissions from LUC and
    deforestation, as counter-part to the separate `CDR Afforestation` sector.
  - The sector `OAE Calcination Emissions` represents the positive
    emissions from OAE (coming from burning synfuels originating from limestone
    calcination)

  After both changes, the sector list for `CO2_em_anthro` becomes:
  1. `Agriculture`
  2. `Energy`
  3. `Industrial`
  4. `Transportation`
  5. `Residential, Commercial, Other`
  6. `Solvents Production and Application`
  7. `Waste`
  8. `International Shipping`
  9. `Deforestation and other LUC`
  10. `OAE Calcination Emissions`
  11. `CDR Afforestation`
  12. `CDR BECCS`
  13. `CDR DACCS`
  14. `CDR EW`
  15. `CDR Industry`
  16. `CDR OAE Uptake Ocean`

  For all other emissions species only the sectors 1-8 apply.
- Adds the total alkalinity additions to the ocean for OAE as a new variable
  `TA_em_anthro` with units of `kmol TA s-1 m-2` into separate gridded files named like
  `TA-em-anthro_input4MIPs_emissions_RESCUE....nc`
- Fixes datatype issues that were breaking cdo

### REMIND-MAgPIE
- MAgPIE
  - Update model version from v4.7.1 to v4.8.0
  - Use of raw land-use change emissions to inform the CO2 budget (see below).
- REMIND
  - In non-overshoot 1.5° scenarios (`PkBudg500-OAE_off`, `PkBudg500-OAE_off`) allow the
    carbon price to slowly decrease after the peak again. This was necessary to attain
    model convergence, while ensuring that cumulative emissions in the year of emissions
    peaking (typically 2045) and in 2100 are equal. This has the consequence that -
    after a short period of net negative CO2 emissions after the peak - CO2 emissions
    will rise again slowly in the second half of the century.
- Update CEDS reporting
  - Change in land-use change (LUC) emissions representation. In previous versions LUC
    CO2 emissions (positive gross emissions `CEDS+|9+
    Sectors|Emissions|CO2|Deforestation and other LUC` and negative afforestation CDR
    `CEDS+|9+ Sectors|Emissions|CO2|CDR Afforestation`) were based on a smoothed MAgPIE
    output variable, in which spikes in single time steps were dampend via a low-pass
    filter function. This smoothing, however, led to inconsistencies in the CO2 budget
    between scenarios with and without overshoot. Therefore, in this release version the
    raw LUC emissions are used instead.
  - Rename `CEDS+|9+ Sectors|Emissions|CO2|Aggregate - Agriculture and LUC` to `CEDS+|9+
    Sectors|Emissions|CO2|Deforestation and other LUC`. Please note
    that for other gases the original sector `Aggregate - Agriculture and LUC` was kept,
    as it comprises the sub-sectors `Agriculture`, `Agricultural Waste Burning`, `Forest
    Burning` and `Grassland Burning`, which are not resolved for `CO2`.
  - Remove positive OAE emissions (coming from burning synfuels originating from
    limestone calcination) from the end-use sectors. Instead the variable `CEDS+|9+
    Sectors|Emissions|CO2|OAE Calcination Emissions` is now required to be used by all
    ESMs to capture these positive emissions from the OAE technology.
  - Add total alkalinity additions to the ocean as variable
    (`RESCUE|OAE|Alkalinity Addition` in `Tmol TA/yr`).

## 2024-04-25

- gridded dataset for 2015-2100 in 10-year for 1 scenario:
  - RESCUE-Tier1-Direct-2023-12-13-PkBudg500-OAE_on
- harmonized data for 2020-2100 in 5-year steps until 2060 and 10-year steps until 2100 for 29 scenarios:
   - RESCUE-Tier1-Sensitivity-2024-04-25-Baseline
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0400-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0450-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0500-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0600-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0750-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp1000-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp1300-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp1700-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp2300-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp3000-OAE_off
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0400-OAE_on
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0450-OAE_on
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0500-OAE_on
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0600-OAE_on
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp0750-OAE_on
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp1000-OAE_on
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp1300-OAE_on
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp1700-OAE_on
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp2300-OAE_on
   - RESCUE-Tier1-Sensitivity-2024-04-25-EocBudg_cp3000-OAE_on
   - RESCUE-Tier1-Direct-2024-04-25-PkBudg500-OAE_off
   - RESCUE-Tier1-Direct-2024-04-25-PkBudg1150-OAE_off
   - RESCUE-Tier1-Direct-2024-04-25-PkBudg500-OAE_on
   - RESCUE-Tier1-Direct-2024-04-25-PkBudg1150-OAE_on
   - RESCUE-Tier1-Direct-2024-04-25-EocBudg500-OAE_off
   - RESCUE-Tier1-Direct-2024-04-25-EocBudg1150-OAE_off
   - RESCUE-Tier1-Direct-2024-04-25-EocBudg500-OAE_on
   - RESCUE-Tier1-Direct-2024-04-25-EocBudg1150-OAE_on

### Gridding
- Add new gridded cdr variables to CO2_em_anthro variable:
  - `CDR Afforestation` (with proposed spatial pattern),
  - `CDR BECCS` (with proposed spatial pattern),
  - `CDR DACCS`,
  - `CDR EW` (no data in Tier 1 scenarios),
  - `CDR Industry`,
  - `CDR OAE` (with proposed spatial pattern)
- Update definition of harmonized variables:
  - `CO2::Aggregate - Agriculture and LUC` contains only positive LUC emissions and is harmonized to GCB 2023 (global)
  - `CO2::CDR Afforestation` is harmonized to the negative component of GCB 2023 (`forest regrowth` at global level)
- Fix datatype of `_FillValue` attribute to float32

### REMIND-MAgPIE
- MAgPIE
  - Update model version from v4.7.0 to v4.7.1
  - Switch to `forestryExo` realization to keep timber area constant
- REMIND
  - Switch from a regional "keep net-zero CO2 emissions after peak"-target to
    a global one. This way we allow individual regions to still generate net
    negative emissions in order to compensate for emissions in other regions,
    as long as global net emissions do not become negative.
  - Activate global 5 Gt CO2/yr OAE bound with GDP-based regional shares.
- Update CEDS reporting
  - Change definition of CDR from re- and afforestation. Before we assumed
    CDR from re- and afforestation is simply the amount of regional net
    negative LUC emissions. Now we explicitly use the natural regrowth in
    `Secondary Forest`, `Other Land` and `Timber Plantations`, as well as in
    forests that were intentionally planted to generate negative emissions,
    that is, via price-incentives `CO2-price AR`, or via specific policy
    targets `NPI_NDC AR`. This is based on the UNFCCC convention that all
    LUC emissions that can be attributed to “human activity” is defined as CDR.

## 2024-03-21

- gridded dataset for 2015-2100 in 10-year for 1 scenario:
  - RESCUE-Tier1-Direct-2023-12-13-PkBudg500-OAE_on

### Gridding

- The separate `CO2_em_removal` variables were integrated as new sectors into the
  `CO2_em_anthro` variable for all types of negative emissions: *Afforestation*,
  *BECCS*, *DACCS*, *EW*, *Industry* and *OAE*.
- The gridded scenario data starts in 2015 (where 2015-2020 derives from a custom
  CEDS2017 extension)
- Consistent data form:
  - Dimensions are ordered `time`, `level` or `sector`, `lat`, `lon`
  - Sector coordinates have guaranteed orders:
    - `{gas}_em_anthro` variables have: `Agriculture`, `Energy`,
      `Industrial`,`Transportation`, `Residential, Commercial, Other`,
      `Solvents Production and Application`, `Waste`, `International Shipping`
    - `CO2_em_anthro` variables have the same sectors, but in addition the negative
      emissions sectors: `CDR Afforestation`, `CDR BECCS`, `CDR DACCS`, `CDR EW`,
      `CDR Industry`, `CDR OAE`
    - `{gas}_em_openburning` has: `Agricultural Waste Burning`, `Forest Burning`,
      `Grassland Burning`, `Peat Burning`
  - Data type is `float32`
  - Time dimension is monthly in the years 2015, 2020, 2030, ..., 2100.

**WARNING**: Since not all proxy discussions have concluded, *Afforestation*, *BECCS*,
*EW* and *OAE* are only provided as nan values in this preliminary review round.

### REMIND-MAgpIE

No updates.

## 2023-12-08

- dataset for 1995-2100 in 10-year timesteps for 6 scenarios.

### Gridding

- Updated filenames and netcdf metadata following the structure in CMIP6
- New shipping proxies by MariTeam
- New CDR proxies for DACCS and Industrial CDR
- Fixed harmonisation and downscaling for incomplete proxies
- Fixed F-Gas split regression
- Fixed uniform grid (720x360)

### REMIND-MAgpIE

- Update MAgPIE model version number from v4.6.7 to v4.7.0
- Activate timber module in MAgPIE to represent managed forests

## 2023-10-11

### Gridding

### REMIND-MAgpIE

- Update REMIND model version
  - Update REMIND version number from v3.1.0 to v3.2.0; in particular improving near term realism within REMIND (effectively reduces remaining carbon budget)
  - Updated assumption on OAE realization, reducing emissions from limestone calcination
  - Remove overshoot scenarios with OAE, since the new assumptions lead to model instabilities
  - Deactivate climate change impacts within MAgPIE
- Update CEDS emissions reporting
  - Fix/Improve emissions reporting to match CEDS historic emissions
  - Reallocate OAE calcination emissions to end-use sectors

# Land Use

Maintained in separate repository by PIK's MAgPIE team, see [here](https://github.com/pik-piam/mrdownscale/blob/main/runner/changelog-rescue.md).
