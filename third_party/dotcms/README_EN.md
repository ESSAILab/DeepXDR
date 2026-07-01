# dotCMS Sample Application Deployment Guide

English | [中文](README.md)

 dotCMS is an open-source enterprise-level Content Management System (CMS) based on Java. This system uses the official Docker image `dotcms/dotcms:22.02` as the base for functional demonstrations. The `rasp-java.tar.gz` file in this directory is the OpenRASP Java agent probe, and its installation package is embedded into the dotCMS application.


## Starting the dotCMS Image

The dotCMS application must be installed on the app-side server in Docker form. For specific usage instructions, refer to the `dotcms` service configuration in the app-side `docker-compose`.

A sample Docker Compose configuration for this image is shown below:
```yaml
  dotcms:
    image: essaigroup/deepxdr-dotcms:v0.3.0
    container_name: app-dotcms
    depends_on:
      elasticsearch:
        condition: service_started
      db:
        condition: service_started
    entrypoint: ["sh"]
    command:
      - -c
      - |
        # [Required] Execute RASP installation. If you build your own RASP package, replace this package when building the application image.
        cd /tmp/rasp-2025-08-05 && java -jar RaspInstall.jar -heartbeat 90 -appid <your-rasp-cloud-appid> -appsecret <your-rasp-cloud-appsecret> -backendurl http://<agent-ip>:8086/ -install /srv/dotserver/tomcat-9.0.41
        cd /tmp && rm -rf rasp-2025-08-05 && rm -rf rasp-java.tar.gz
        exec /srv/entrypoint.sh
    environment:
        "CATALINA_OPTS": '-Xmx2g -Xms1g'
        "DB_BASE_URL": "jdbc:postgresql://db/dotcms"
        "DB_USERNAME": 'dotcmsdbuser'
        "DB_PASSWORD": 'password'
        "DOT_ES_AUTH_BASIC_PASSWORD": 'admin'
        "DOT_ES_ENDPOINTS": 'http://elasticsearch:9200'
        "DOT_INITIAL_ADMIN_PASSWORD": 'admin'
    volumes:
      - cms-shared:/srv/dotserver
      - ./dotcms/starter.zip:/srv/dotserver/tomcat-9.0.41/webapps/ROOT/starter.zip
    ports:
      - "8080:8080"
      - "8443:8443"
    networks:
      - db_net
      - es_net
```

Notes:
Modify the configuration in the `dotcms` service section:

```yaml
-appid <your-rasp-cloud-appid>
-appsecret <your-rasp-cloud-appsecret>
-backendurl http://<your-agent-host-ip>:8086/
```

You need to update the values of the three fields above: `app_id`, `app_secret`, and `backend_url`.
These three field values are obtained from the cloud control management backend after it is deployed on the defense-side host, under **Management Backend > Add Host**.

**Example of the original configuration:**
```bash
java -jar RaspInstall.jar -heartbeat 90 -appid <your-rasp-cloud-appid> -appsecret <your-rasp-cloud-appsecret> -backendurl http://<your-agent-host-ip>:8086/ -install /path/to/tomcat
```

Start the image:
```bash
docker-compose -f docker-compose-app.yml up -d dotcms
```

## Building the dotCMS Image

```bash
cd dotcms
docker build -t essaigroup/deepxdr-dotcms:v0.3.0 .
```
If this image is already provided, skip this step.

## Notes

The placeholder `<agent-ip>` above must be replaced with the actual IP address of the agent-side server.
