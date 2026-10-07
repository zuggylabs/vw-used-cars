#!/bin/python3

# Superseded by the Docker watcher in this folder (see README.md).
# This script calls the old search address, which now returns 404.

## Config
url = "https://usedcars.volkswagen.co.uk/en/used-cars/volkswagen/model-search?country=gb&lat=51.503353&lon=-0.127704&unitSystem=imperial&currency=GBP&customer=&mkey=47-11272-558%7C%7C47-11269-350&sort=distance%3AASC&groupTrim=1&limiter=dkey%5B47-11269-350%3A3%5D&mcategory=all&zip=SW1A+2AA&radius=8047&price_from=&price_to=&km_from=&km_to=27000&reg_date_from=&reg_date_to=&doors_grouped=5&cylinderCapacity_to=&gears=1%7C%7C7&drive=&kw_from=&gas=&consCombined_from=&vehiclestatus=100&manufacturer=65&color%5B%5D=14&trim=2904%3AR"
ignoreplates = ['AB12CDE', 'FG34HIJ', 'KL56MNO']

## Functions
def is_not_blank(s):
    return bool(s and not s.isspace())

## Load libraries
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager
from bs4 import BeautifulSoup
import json

## Load "optional extras" json file in dictionary
jsonfile = open('option_info.json',)
jsondict = json.load(jsonfile)
jsonfile.close()

## Setup browser
browseroptions = Options()
browseroptions.headless = True
driver = webdriver.Firefox(options=browseroptions, executable_path=GeckoDriverManager().install())
driver.get(url)
driver.implicitly_wait(10)

## Accept cookies
driver.find_element(By.ID, "bannerAcceptButton").click()

## Loop through loading more results
try:
  while WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.ID, "load-more"))):
    driver.find_element(By.ID, "load-more").click()

## Continue at end of loop without error. Proabably a better way to do this ¯\_(ツ)_/¯
except:
  pass

## Load page data into beautiful soup and process
finally:
  soup = BeautifulSoup(driver.page_source.encode('utf-8'), "html.parser")
  driver.quit()
  results = soup.find(id="results")
  car_elements = results.find_all("article", class_="search-results-vehicle")

## Setup counts
vehiclecount = 0
unknownoptions = 0
unknownowners = 0
rawprice = 0

for car in car_elements:
  plate = car.attrs['data-vrm']
  title = car.find("h2", class_="title").text
  description = car.find("h3", class_="description").text
  price = car.find("div", class_="price").text
  ## In case the mileage field is empty
  mileagegrab = car.find("li", {"title": "Mileage"})
  if mileagegrab is not None:
    mileagearray = (mileagegrab.text).split()
    mileage = mileagearray[1]
  else:
    mileage = "UNKNOWN"
  ## In case the previous owners field is empty
  ownersgrab = car.find("li", {"title": "Previous Owners"})
  if ownersgrab is not None:
    ownersarray = (ownersgrab.text).split()
    if ownersarray[2] == "-":
      owners = "UNKNOWN"
    else:
      owners = ownersarray[2]
  else:
    owners = "UNKNOWN"
  regdatearray = (car.find("li", {"title": "1st reg. date"}).text).split()
  regmonth = regdatearray[3]
  regyear = regdatearray[4]
  location = car.find("span", class_="dealer-name").text
  carurlfull = car.find("a", class_="mdx-gtm-srp-open-vdp")
  carurl = "https://usedcars.volkswagen.co.uk" + carurlfull.attrs['href']

  ## Match up car options from json file/dictionary
  caroptions = "UNKNOWN"

  for optionsentry in jsondict['options_by_plate']:
    if optionsentry['plate'] == plate:
      caroptions = optionsentry['options']
      break

  ## Exclude cars by number plate and count and output results
  if plate not in ignoreplates:
    vehiclecount += 1
    print("Plate:", plate)
    print("Title:", title)
    print("Description:", description)
    print("Price:", price)
    rawprice = rawprice + int((price.replace(',', '')).replace('£', ''))
    print("Mileage:", mileage)
    print("Options:", caroptions)
    if caroptions == "UNKNOWN":
      unknownoptions += 1
    print("Reg month:", regmonth)
    print("Reg year:", regyear)
    print("Previous owners:", owners)
    if owners == "UNKNOWN":
      unknownowners += 1
    print("Location:", location)
    print("URL:", carurl)
    print()

## Output summary and counts
print()
print("=======================")
print("==      Summary      ==")
print("=======================")
print()
print("Total cars:", vehiclecount)
print("Average price: £{:0,}".format(round(rawprice/vehiclecount)))
print("Unknown options count:", unknownoptions)
print("Unknown owners count:", unknownowners)
