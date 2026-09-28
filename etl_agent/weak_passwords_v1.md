# 离线弱密码表 v1

`weak_passwords_v1.txt` 是随代码固定版本的公开样例集，共 207 条：取自 [SecLists 10k-most-common.txt](https://github.com/danielmiessler/SecLists/blob/master/Passwords/Common-Credentials/10k-most-common.txt) 的前 200 条，以及 [SecLists NCSC 100k 列表](https://github.com/danielmiessler/SecLists/blob/master/Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt) 中的 7 条 15 字符以上样例。上游项目采用 [MIT License](https://github.com/danielmiessler/SecLists/blob/master/LICENSE)。文件只用于本地账户设密时的大小写不敏感匹配，不随请求访问网络。

这是一份有限的离线快照，不保证覆盖全部已泄露密码。长度不足 15 字符即使不在表中也会拒绝；账户名及设密时已有的项目名称另行校验。后续扩表应发布新版本并重新测试，不静默改变现有版本的含义。真实 PostgreSQL 环境中的账户初始化与策略执行仍待联调。
