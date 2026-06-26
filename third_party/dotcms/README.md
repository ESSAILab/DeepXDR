# dotcms示例应用部署文档

 dotCMS是一款基于Java开发的开源企业级内容管理系统（CMS），本系统基于该应用的官方docker镜像dotcms/dotcms:22.02为基础，进行系统功能的演示，其中本目录下的rasp-java.tar.gz为openrasp java agent探针，它的安装包会被内置到dotcms应用中。
 

## dotcms镜像启动

dotcms应用需要以docker形式安装在app侧服务器上，具体使用方法参见应用侧docker-compose中的dotcms服务配置。

docker-compose中该镜像配置示例展示如下 ：
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
        # [Required]执行 RASP 安装，如用户自行编译rasp安装包，则需在构建应用镜像时替换该包
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

注意：  
修改dotcms服务部分的配置信息：

```yaml
-appid <your-rasp-cloud-appid>
-appsecret <your-rasp-cloud-appsecret>
-backendurl http://<your-agent-host-ip>:8086/
```

需要修改如上3个字段`app_id`/`app_secret`/`backend_url`的值，
3个字段值的来源是在防御端主机部署好云控管理后台后，在管理后台-添加主机处查看。

**展示的原始配置信息举例如下：**
```bash
java -jar RaspInstall.jar -heartbeat 90 -appid <your-rasp-cloud-appid> -appsecret <your-rasp-cloud-appsecret> -backendurl http://<your-agent-host-ip>:8086/ -install /path/to/tomcat
```

启动镜像：
```bash
docker-compose -f docker-compose-app.yml up -d dotcms
```

## dotcms镜像构建方法

```bash
cd dotcms
docker build -t essaigroup/deepxdr-dotcms:v0.3.0 .
```
如果该镜像已经提供，则跳过此步骤。

## 注意事项

上面出现的占位符 `<agent-ip>`需要替换成实际agent侧服务器的ip地址。