# Emissions

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

Maintained in separate repository by PIK's MagPIE team.

## 2023-12-08

- dataset for 1995-2100 in 5-year timesteps for all REMIND-MAgPIE scenarios used for the emissions
- added metadata to nc files
- management.nc: added fulwd, rndwd
- transitions.nc: reporting all LUH variables incl. wood harvest variables
- all transitions are gross transitions
- transitions in 2100 are net-zero gross transitions (to be used for extended (2100-2300) scenarios)
- cover all LUH cells (e.g. Greenland was missing before)


## 2023-10-11

- dataset for 1995-2100 in 5-year timesteps for one scenario
- states.nc: reporting all LUH variables except secma, secmb
- management.nc: reporting all LUH variables except fulwd, rndwd, combf, flood, fharv_c3per, fharv_c4per
- additionally reporting 2nd gen biofuel (crpbf2_c3per, crpbf2_c4per) and managed forests (manaf) in management.nc
852 bytes transferred in 3 seconds (281 B/s)
