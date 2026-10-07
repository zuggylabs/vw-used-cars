# VW used stock watcher

This project started out of a fairly simple motivation: I wanted to buy a car, but found the website lacking some of the functionality I wanted. What began as a small Selenium scraper quickly became a useful tool for monitoring vehicle listings, initially just writing the results to a text file. This made it possible to spot new vehicles as they appeared, as well as interesting changes over time such as price adjustments, mileage changes, and other listing behaviour that would otherwise be easy to miss. In the end I found a car and stopped working on the script, but the original idea was always to take it further.

The legacy scrape.py file remains in the repository as a record of where the project started, but is now defunct. This version of the project is pretty much what I was originally working towards: a Dockerised, web-based watcher that automatically scrapes the site on a schedule, keeps historical data, and highlights changes between scrapes. There is still plenty that could be added, such as notifications when interesting changes are detected.

## Features

- Automatically scrape multiple VW used-car searches on a schedule.
- Web interface for viewing current and historical listings.
- Detect new, removed and price-reduced vehicles.
- Track changes to listings, including mileage and price.
- Keep historical snapshots and number-plate history.
- Hide cars you are no longer interested in without stopping them being monitored.
- Record and compare vehicle options independently of the dealer's often-incomplete descriptions.
- Run entirely in Docker with persistent data stored locally.
- Trigger a scrape manually without waiting for the scheduled run.

## Run it

```bash
docker compose up -d --build
```

Open http://localhost:8080

The first scrape starts when the container starts. After that it runs every day at 08:00 UK time. Change `schedule` in `config.yaml` (five fields: minute hour day month weekday) and recreate the container:

```bash
docker compose up -d --build
```

Changes to the search list are read on the next scrape without a rebuild. Use **Run scrape now** on the page, or:

```bash
docker compose run --rm watcher python -m watcher once
```

Snapshots and the plate history are kept in `data/`.

## What you will see

- **Price reduced**, **New**, and **Removed** against the previous run. Removed usually means the car has been sold or delisted.
- The full list from that scrape.
- A plate history at `/search/<id>/history`.
- The options you have recorded for each car, as green tags in the list, and how many cars have not been checked yet. See [Options](#options).
- **Hide** next to any car takes it out of the list once you have decided it is not for you. Hidden cars are still scraped and compared, so their price changes and removal still show in the change sections, greyed out, and in the plate history. They are listed under **Hidden cars** at the bottom of the search page, where **Show** puts them back. Hidden cars are saved per search in `data/<search id>/hidden.json`.

A failed scrape is kept off the record. Cars are not marked as sold just because the page could not be read. The failed HTML is saved under `data/debug/`.

## Searches

Searches are managed on the home page.

- **Add:** set the search up on [usedcars.volkswagen.co.uk](https://usedcars.volkswagen.co.uk/en/vehicle_search/volkswagen/all-models), copy the address of the results page, and paste it into **Add a search**. The name is optional; one is made up from the colour, model, and trim if you leave it blank. The new search is scraped straight away and then on the schedule with the rest.
- **Remove:** use **Remove** on its card, or **Remove this search** on its page. Its saved scrapes stay in `data/`.

The list is kept in `data/searches.json`. A fresh install starts with no searches. Mileage on the current site is in miles.

## Options

Dealers are not good at listing a car's options. One car might be described as having "19in alloys, leather", another just says "great spec". The listings don't separate optional extras from standard equipment either. If you are using something like this to wait for a specific car it's likely you know the options available for the car you are after and can tell from the photos eg the glass of a sunroof, the pattern of an alloy wheel, comfort menu for DCC, a Dynaudio speaker grille. The options feature is where you write down what you have seen, so you can compare cars on what they actually have rather than on what the advert says.

There are two parts.

**The options list** is one list shared by every search. It's under **Options to look for** at the bottom of the home page. Add the things you care about, for example *Panoramic sunroof*, *19" Pretoria alloys*, *Vienna leather*, or *DCC*. Rename an option by editing its name. Clear the name to remove it, which also removes it from every car. Click **Save options** when you are done. A fresh install starts with an empty list.

**Each car's options.** In the car list on a search page, each car has an **Edit options** link. It opens a page with a link to the Volkswagen listing so you can go through the photos. Then mark each option as:

- **Yes:** you can see it is fitted.
- **No:** you can see it is not.
- **?:** you haven't checked yet, or the photos don't show it.

After saving, the car's fitted options show as green tags in the list, with a count of any still marked **?**. Only the first three tags are shown, in the order of the options list, followed by **+N more**, which shows the rest when clicked. A car that has never been checked shows **Not checked**, and the page tells you how many cars in the search still need looking at. Adding a new option to the list later just leaves it as **?** on cars you have already checked.

What you record belongs to the car, not to a search. It is keyed by number plate, so it appears in every search the car turns up in. It is kept if the car leaves the listing and comes back. It sits alongside hiding, so you can record options on a car and still hide it.

The scrape copies each car's fitted options into its snapshot. The text summary in the log includes a list of cars with nothing checked yet.

Everything is saved in `data/car_options.json`.
