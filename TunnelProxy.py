import socket
import socketserver
import select
import requests
import sys
import queue
import threading

import random

# 用来存储代理的socket
SocketQueue = queue.Queue(300)

# 用来储存客户端发送隧道请求的包
askdata = bytes()


class ThreadedTCPRequestHandler(socketserver.BaseRequestHandler):

    def handle(self):
        global SocketQueue

        # 与客户端建立链路
        self.link_prepare()

        wait_repackage = []

        read_only = [self.request]

        if SocketQueue.empty():
            print("代理池为空，断开当前链接")
            return
        read_only.append(SocketQueue.get())

        while True:
            try:
                # 采用select监听socket是否可读
                r, w, e = select.select(read_only, [], [], 1)

                # 判断触发可读事件的是不是与客户端交互的socket
                for read in r:
                    if read == self.request:
                        data = self.request.recv(1024)
                        print("从", self.client_address, "得到数据")
                        # print("客户端发送%s：" % data)
                        # 判断是否是请求断开
                        if not data:
                            print("客户端", self.client_address, "断开连接")
                            break
                        # 判断socket是否发生错误
                        elif data == -1:
                            print("socket发生错误！！！！")
                            break
                        # 不是上面两个就是收到的正常数据了，与客户端交互的socket收到数据，肯定是客户端发送的，直接转到代理就行了
                        else:
                            # 随机从与代理连接的socket中得到一个，转发数据，并将其加入等待响应的列表中
                            proxy_socket = read_only[1]
                            proxy_socket.sendall(data)
                            print("转发数据到代理")
                            # wait_repackage.append(proxy_socket)

                    # 既然不是与客户端交互的socket，那就是与代理交互的socket了
                    else:
                        data = read.recv(1024)
                        print("从",read.getpeername, "得到数据")
                        # print("代理返回%s：" % data)
                        # 判断是否亲请求断开
                        if not data:
                            # read.close()
                            print("远程代理", read.getpeername(), "断开连接")
                            return
                        elif data == -1:
                            print("socket发生错误！！！！")
                            return
                        else:
                            self.request.sendall(data)
                            print("转发数据到客户端")

            except ConnectionAbortedError:
                print("客户端", self.client_address, "强行终止链接")
                break
            except ConnectionResetError as e:
                print("代理断开连接", e)
                break

        # 客户端断开链接时，断开与代理服务器的链接
        read_only[1].close()

    # 建立客户端-本程序
    def link_prepare(self):
        global askdata

        data = self.request.recv(1024)
        # print("客户端发送：%s" % data)

        if data[0:7].decode() == "CONNECT":
            askdata = data
            message = "{HTTP/1.1 200 Connection Established\r\n\r\n".encode()
            self.request.sendall(message)
            print("客户端", self.client_address, "连接成功")

        else:
            sys.exit()


class RandomSocket:
    def __init__(self):
        global askdata
        while True:
            # 由于这个比服务器类对象先启动，askdata未来得及赋值，就会发送空导致没有数据返回从而堵塞
            if askdata.decode() == '':
                continue
            self.link_proxy(self.get_proxysocket())

    # 随机从代理池获取一个地址
    def get_proxysocket(self):
        # print("开始从代理池获取ip")
        proxy = requests.get("http://127.0.0.1:5010/get/").json().get("proxy").split(":")
        proxy[1] = int(proxy[1])
        address = tuple(proxy)
        # print("获取随机代理", address)
        return address

    # 检验地址是否可以建立隧道，如果可以就加入队列
    def link_proxy(self, address):
        global askdata, SocketQueue
        proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # # 设置心跳包保持长连接
        # proxy_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, True)
        #
        # # 开启保活机制，1分钟后对方还没有反应，开始探测连接是否存在。30秒钟探测一次，默认探测10次，失败则断开
        # proxy_socket.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 60*1000, 30*1000))

        try:
            proxy_socket.connect(address)  # 连接服务器
            proxy_socket.sendall(askdata)  # 发送数据
            message = proxy_socket.recv(1024)
            if message[9:12].decode() == "200":
                # 将可以连接的socket保存到队列中
                SocketQueue.put(proxy_socket)
                # print("长度",SocketQueue.qsize())
                # print("代理", proxy_socket.getpeername(), "加入队列")
        except TimeoutError:
            return
        except ConnectionResetError:
            # 是服务器端因为某种原因关闭了Connection，而客户端依然在读写数据，此时服务器会返回复位标志“RST”，“RST”标志表示我不再发送数据也不接收数据了
            # print("代理", proxy_socket.getpeername(), "断开了连接")
            return


class MyThread(threading.Thread):
    def __init__(self, fun):
        super().__init__()
        self.fun = fun

    def run(self):
        eval(self.fun)


if __name__ == "__main__":
    # Port 0 means to select an arbitrary unused port
    HOST, PORT = "127.0.0.1", 9999

    # 存储开启的每一个线程实例
    thread = []

    # 开启线程扫描
    thrednum = 10
    for _ in range(thrednum):
        # 参数是要开启线程的函数带参数
        t = MyThread("RandomSocket()")
        thread.append(t)
        t.start()

    # 创建服务器
    print("开启服务器")
    server = socketserver.ThreadingTCPServer((HOST, PORT), ThreadedTCPRequestHandler)
    server.serve_forever()

    # 等待所有线程完成
    for t in thread:
        t.join()
