# opml2json

This is a Python Flask application that retrieves or reads and uploaded OPML file, aggregates and parses the RSS files listed in the OPML, then returns the results as JSON.

- results are pages, default 20 listings per page, with a 'cursor' time stamp to start the next page
- results are sorted chronologically
- aggregated RSS feeds are cached and retrieved from the origin server no more than once an hour

The repository includes a simple web form for sending requests to the script. An example of this form may be seen at https://opml2json.downes.ca and you are free to use this service if you wish, instead of downloading and installing this application.

This repository contains:

- test.opml - this is a simple OPML page used for testing. I have an instance of this page hosted at https://www.downes.ca/test.opml

- hello.py - a server side python script that provides the OPML2JSON service. Install it as a standalone application on a web server. It provides an interface into which you can provide the URL of an OPML file or upload one from your desktop. It will aggregate the RSS feeds listed in the file, sort them, and then present the results as a JSON feed, which you can use in your website or application. Feel free to change the name; I just went with the default. If you don't feel like downloading and installing your own Python script, I host an instance of this script here: https://opml2json.downes.ca 

- opml2json.html - an HTML page demonstrating how you can use Javascript to fetch the results from the OPML2JSON service and present them in a readable format. As written, it uses the two pages hosted on downes.ca but you can of course edit it. If you want to use your own OPML file, change the URL from https://www.downes.ca/test.opml to the URL of your own HTML file. If you want to use your own hosted Python script, change the URL from https://opml2json.downes.ca to the URL for your own script.

I will continue to maintain https://opml2json.downes.ca as a public service until and unless it becomes too expensive to do so. I'm open to pull requests that improve the efficiency and usefulness of this service.
