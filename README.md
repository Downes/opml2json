# opml2json

This is a Python Flask application that retrieves or reads and uploaded OPML file, aggregates and parses the RSS files listed in the OPML, then returns the results as JSON.

- results are pages, default 20 listings per page, with a 'cursor' time stamp to start the next page
- results are sorted chronologically
- aggregated RSS feeds are cached and retrieved from the origin server no more than once an hour

The repository includes a simple web form for sending requests to the script. An example of this form may be seen at https://opml2json.downes.ca and you are free to use this service if you wish, instead of downloading and installing this application.

A demonstration web page with Javascript that defaults to the https://opml2json.downes.ca service using https://www.downes.ca/test.opml as a test OPML file is also included with this repository. You can see this page in operation at https://www.downes.ca/opml2json.html

I will continue to maintain https://opml2json.downes.ca as a public service until and unless it becomes too expensive to do so. I'm open to pull requests that improve the efficiency and usefulness of this service.
