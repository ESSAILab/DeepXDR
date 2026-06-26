# 使用nginx负载均衡、限速、客制化出错页面

## nginx部署和配置

### 安装nginx
1. 系统默认包安装
```bash
sudo apt update
sudo apt install nginx

或者
yum update
yum install nginx
```

2. 编译安装
```bash
wget http://nginx.org/download/nginx-1.22.1.tar.gz
tar -zxvf nginx-1.22.1.tar.gz
cd nginx-1.22.1
./configure
make
sudo make install
```

如果想添加模块，例如使用ngx_dynamic_upstream 模块，需要下载该模块代码和对应的nginx源码一起编译安装。
```bash
# 安装依赖
sudo apt install -y build-essential libpcre3 libpcre3-dev zlib1g zlib1g-dev openssl libssl-dev git

# 创建工作目录
mkdir ~/nginx-build && cd ~/nginx-build

# 下载 Nginx 源码（推荐稳定版）
wget http://nginx.org/download/nginx-1.28.0.tar.gz
tar -zxvf nginx-1.28.0.tar.gz

# 下载 ngx_dynamic_upstream 模块
git clone https://github.com/cubicdaiya/ngx_dynamic_upstream.git

# 编译
cd nginx-1.28.0/
./configure \
  --prefix=/usr/local/nginx \
  --sbin-path=/usr/local/sbin/nginx \
  --conf-path=/usr/local/nginx/nginx.conf \
  --error-log-path=/usr/local/nginx/logs/error.log \
  --http-log-path=/usr/local/nginx/logs/access.log \
  --pid-path=/usr/local/nginx/nginx.pid \
  --with-http_ssl_module \
  --with-http_v2_module \
  --with-http_realip_module \
  --with-http_stub_status_module \
  --with-http_gzip_static_module \
  --with-stream \
  --with-stream_ssl_module \
  --with-threads \
  --with-file-aio \
  --add-module=../ngx_dynamic_upstream

# 安装
# 编译（多核加速）
make -j$(nproc)

# 安装
sudo make install
```

### 配置nginx

使用系统包安装的nginx配置文件是`/etc/nginx/nginx.conf`和`/etc/nginx/sites-available/default`；编译安装的nginx配置文件是`/usr/local/nginx/nginx.conf`或者`/usr/local/nginx/conf/nginx.conf`。

下面均以`/usr/local/nginx/conf/nginx.conf`为例，本目录下的`nginx.conf`文件，里面有关于限速的部分，关键字为`limit_req`；同时配置了`client_max_body_size`、`client_body_timeout`、`proxy_request_buffering on`和较短的代理超时，用于限制大请求和慢速上传占用后端连接。具体的上传大小限制可按业务需要调整，但不要设置为`0`。另外，还有客制化403页面，关键字为`403`。这是MCP Server阻断IP时返回的页面。出错页面就是custom_403.html，该文件应放置在nginx部署环境的`/usr/share/nginx/html/`目录下。

MCPServer最终会把要阻塞的IP写入文件 /etc/nginx/blocked_ips.conf 
```
# /etc/nginx/blocked_ips.conf  文件内容格式如下：
172.18.8.110 1; 

```

