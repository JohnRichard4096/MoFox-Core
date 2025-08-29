from enum import Enum

class NapcatEvent(Enum):
    """
    napcat插件事件枚举类
    """
    class ON_RECEIVED(Enum): 
        """
        该分类下均为消息接受事件，只能由napcat_plugin触发
        """
        TEXT = "napcat_on_received_text"    
        '''接收到文本消息'''
        FACE = "napcat_on_received_face"    
        '''接收到表情消息'''
        REPLY = "napcat_on_received_reply"  
        '''接收到回复消息'''
        IMAGE = "napcat_on_received_image"  
        '''接收到图像消息'''
        RECORD = "napcat_on_received_record"    
        '''接收到语音消息'''
        VIDEO = "napcat_on_received_video"  
        '''接收到视频消息'''
        AT = "napcat_on_received_at"    
        '''接收到at消息'''
        DICE = "napcat_on_received_dice"    
        '''接收到骰子消息'''
        SHAKE = "napcat_on_received_shake"  
        '''接收到屏幕抖动消息'''
        JSON = "napcat_on_received_json"    
        '''接收到JSON消息'''
        RPS = "napcat_on_received_rps"  
        '''接收到魔法猜拳消息'''
        FRIEND_INPUT = "napcat_on_friend_input" 
        '''好友正在输入'''
    
    class ACCOUNT(Enum):
        """
        该分类是对账户相关的操作，只能由外部触发，napcat_plugin负责处理
        """
        SET_PROFILE = "napcat_set_qq_profile"   
        '''设置账号信息
        
        Args:
            nickname (Optional[str]): 名称(必须)
            personal_note (Optional[str]): 个性签名
            sex ('0'|'1'|'2'): 性别
            raw (Optional[dict]): 原始请求体

        Returns:
            dict:  {
            "status": "ok",
            "retcode": 0,
            "data": {
                "result": 0,
                "errMsg": "string"
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }

        '''
        GET_ONLINE_CLIENTS = "napcat_get_online_clients"    
        '''获取当前账号在线客户端列表
        
        Args:
            no_cache (Optional[bool]):  是否不使用缓存
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": [
                "string"
            ],
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SET_ONLINE_STATUS = "napcat_set_online_status" 
        '''设置在线状态
        
        Args:
            status (Optional[str]): 状态代码(必须)
            ext_status (Optional[str]): 额外状态代码,默认为0
            battery_status (Optional[str]): 电池信息,默认为0
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": null,
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_FRIENDS_WITH_CATEGORY = "napcat_get_friends_with_category" 
        '''获取好友分组列表
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": [
                {
                    "categoryId": 0,
                    "categorySortId": 0,
                    "categoryName": "string",
                    "categoryMbCount": 0,
                    "onlineCount": 0,
                    "buddyList": [
                        {
                            "birthday_year": 0,
                            "birthday_month": 0,
                            "birthday_day": 0,
                            "user_id": 0,
                            "age": 0,
                            "phone_num": "string",
                            "email": "string",
                            "category_id": 0,
                            "nickname": "string",
                            "remark": "string",
                            "sex": "string",
                            "level": 0
                        }
                    ]
                }
            ],
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SET_AVATAR = "napcat_set_qq_avatar" 
        '''设置头像
        
        Args:
            file (Optional[str]): 文件路径或base64(必需)
            raw (Optional[dict]): 原始请求体

        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": null,
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SEND_LIKE = "napcat_send_like"  
        '''点赞
        
        Args:
            user_id (Optional[str|int]): 用户id(必需)
            times (Optional[int]): 点赞次数,默认1
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": null,
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SET_FRIEND_ADD_REQUEST = "napcat_set_friend_add_request"    
        '''处理好友请求
        
        Args:
            flag (Optional[str]): 请求id(必需)
            approve (Optional[bool]): 是否同意(必需)
            remark (Optional[str]): 好友备注(必需)
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": null,
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SET_SELF_LONGNICK = "napcat_set_self_longnick"  
        '''设置个性签名
        
        Args:
            longNick (Optional[str]): 内容(必需)
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "result": 0,
                "errMsg": "string"
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_LOGIN_INFO = "napcat_get_login_info"  
        '''获取登录号信息
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "user_id": 0,
                "nickname": "string"
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_RECENT_CONTACT = "napcat_get_recent_contact"    
        '''最近消息列表

        Args:
            count (Optional[int]): 会话数量
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": [
                {
                    "lastestMsg": {
                        "self_id": 0,
                        "user_id": 0,
                        "time": 0,
                        "real_seq": "string",
                        "message_type": "string",
                        "sender": {
                            "user_id": 0,
                            "nickname": "string",
                            "sex": "male",
                            "age": 0,
                            "card": "string",
                            "role": "owner"
                        },
                        "raw_message": "string",
                        "font": 0,
                        "sub_type": "string",
                        "message": [
                            {
                                "type": "text",
                                "data": {
                                    "text": "string"
                                }
                            }
                        ],
                        "message_format": "string",
                        "post_type": "string",
                        "group_id": 0
                    },
                    "peerUin": "string",
                    "remark": "string",
                    "msgTime": "string",
                    "chatType": 0,
                    "msgId": "string",
                    "sendNickName": "string",
                    "sendMemberName": "string",
                    "peerName": "string"
                }
            ],
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_STRANGER_INFO = "napcat_get_stranger_info"  
        '''获取(指定)账号信息
        
        Args:
            user_id (Optional[str|int]): 用户id(必需)
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "user_id": 0,
                "uid": "string",
                "uin": "string",
                "nickname": "string",
                "age": 0,
                "qid": "string",
                "qqLevel": 0,
                "sex": "string",
                "long_nick": "string",
                "reg_time": 0,
                "is_vip": true,
                "is_years_vip": true,
                "vip_level": 0,
                "remark": "string",
                "status": 0,
                "login_days": 0
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_FRIEND_LIST = "napcat_get_friend_list"  
        '''获取好友列表
        
        Args:
            no_cache (Opetional[bool]): 是否不使用缓存
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": [
                {
                    "birthday_year": 0,
                    "birthday_month": 0,
                    "birthday_day": 0,
                    "user_id": 0,
                    "age": 0,
                    "phone_num": "string",
                    "email": "string",
                    "category_id": 0,
                    "nickname": "string",
                    "remark": "string",
                    "sex": "string",
                    "level": 0
                }
            ],
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_PROFILE_LIKE = "napcat_get_profile_like"    
        '''获取点赞列表
        
        Args:
            user_id (Opetional[str|int]): 用户id,指定用户,不填为获取所有
            start (Opetional[int]): 起始值
            count (Opetional[int]): 返回数量
            raw (Optional[dict]): 原始请求体

        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "uid": "string",
                "time": 0,
                "favoriteInfo": {
                    "total_count": 0,
                    "last_time": 0,
                    "today_count": 0,
                    "userInfos": [
                        {
                            "uid": "string",
                            "src": 0,
                            "latestTime": 0,
                            "count": 0,
                            "giftCount": 0,
                            "customId": 0,
                            "lastCharged": 0,
                            "bAvailableCnt": 0,
                            "bTodayVotedCnt": 0,
                            "nick": "string",
                            "gender": 0,
                            "age": 0,
                            "isFriend": true,
                            "isvip": true,
                            "isSvip": true,
                            "uin": 0
                        }
                    ]
                },
                "voteInfo": {
                    "total_count": 0,
                    "new_count": 0,
                    "new_nearby_count": 0,
                    "last_visit_time": 0,
                    "userInfos": [
                        {
                            "uid": "string",
                            "src": 0,
                            "latestTime": 0,
                            "count": 0,
                            "giftCount": 0,
                            "customId": 0,
                            "lastCharged": 0,
                            "bAvailableCnt": 0,
                            "bTodayVotedCnt": 0,
                            "nick": "string",
                            "gender": 0,
                            "age": 0,
                            "isFriend": true,
                            "isvip": true,
                            "isSvip": true,
                            "uin": 0
                        }
                    ]
                }
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        DELETE_FRIEND = "napcat_delete_friend"  
        '''删除好友
        
        Args:
            user_id (Opetional[str|int]): 用户id(必需)
            temp_block (Opetional[bool]): 拉黑(必需)
            temp_both_del (Opetional[bool]): 双向删除(必需)
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "result": 0,
                "errMsg": "string"
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_USER_STATUS = "napcat_get_user_status"  
        '''获取(指定)用户状态
        
        Args:
            user_id (Opetional[str|int]): 用户id(必需)
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "status": 0,
                "ext_status": 0
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_STATUS = "napcat_get_status"    
        '''获取状态
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "online": true,
                "good": true,
                "stat": {}
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_MINI_APP_ARK = "napcat_get_mini_app_ark"    
        '''获取小程序卡片
        
        Args:
            type (Optional[str]): 类型(如bili、weibo,必需)
            title (Optional[str]): 标题(必需)
            desc (Optional[str]): 描述(必需)
            picUrl (Optional[str]): 图片URL(必需)
            jumpUrl (Optional[str]): 跳转URL(必需)
            webUrl (Optional[str]): 网页URL
            rawArkData (Optional[bool]): 是否返回原始ark数据
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "appName": "string",
                "appView": "string",
                "ver": "string",
                "desc": "string",
                "prompt": "string",
                "metaData": {
                    "detail_1": {
                        "appid": "string",
                        "appType": 0,
                        "title": "string",
                        "desc": "string",
                        "icon": "string",
                        "preview": "string",
                        "url": "string",
                        "scene": 0,
                        "host": {
                            "uin": 0,
                            "nick": "string"
                        },
                        "shareTemplateId": "string",
                        "shareTemplateData": {},
                        "showLittleTail": "string",
                        "gamePoints": "string",
                        "gamePointsUrl": "string",
                        "shareOrigin": 0
                    }
                },
                "config": {
                    "type": "string",
                    "width": 0,
                    "height": 0,
                    "forward": 0,
                    "autoSize": 0,
                    "ctime": 0,
                    "token": "string"
                }
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SET_DIY_ONLINE_STATUS = "napcat_set_diy_online_status"  
        '''设置自定义在线状态
        
        Args:
            face_id (Optional[str|int]): 表情ID(必需)
            face_type (Optional[str|int]): 表情类型
            wording (Optional[str]):描述文本
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": "string",
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
    
    class MESSAGE(Enum):
        """
        该分类是对信息相关的操作，只能由外部触发，napcat_plugin负责处理
        """
        SEND_PRIVATE_MSG = "napcat_send_private_msg"    
        '''发送私聊消息
        
        Args:
            user_id (Opetional[str|int]): 用户id(必需)
            message (Opetional[str]): 消息object(必需)
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "message_id": 0
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SEND_POKE = "napcat_send_poke"    
        '''发送戳一戳
        
        Args:
            group_id (Optional[str|int]): 群号
            user_id (Optional[str|int]): 对方QQ号(必需)
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": null,
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        DELETE_MSG = "napcat_delete_msg"    
        '''撤回消息

        Args:
            message_id (Optional[str|int]): 消息id(必需)
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": null,
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_GROUP_MSG_HISTORY = "napcat_get_group_msg_history"  
        '''获取群历史消息
        
        Args:
            group_id (Optional[str|int]): 群号(必需)
            message_seq (Optional[str|int]): 消息序号,0为最新
            count (Optional[int]): 获取数量
            reverseOrder (Optional[bool]): 是否倒序
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "messages": [
                    {
                        "self_id": 0,
                        "user_id": 0,
                        "time": 0,
                        "message_id": 0,
                        "message_seq": 0,
                        "real_id": 0,
                        "real_seq": "string",
                        "message_type": "string",
                        "sender": {
                            "user_id": 0,
                            "nickname": "string",
                            "sex": "male",
                            "age": 0,
                            "card": "string",
                            "role": "owner"
                        },
                        "raw_message": "string",
                        "font": 0,
                        "sub_type": "string",
                        "message": [
                            {
                                "type": "text",
                                "data": {
                                    "text": "string"
                                }
                            }
                        ],
                        "message_format": "string",
                        "post_type": "string",
                        "group_id": 0
                    }
                ]
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_MSG = "napcat_get_msg"  
        '''获取消息详情
        
        Args: 
            message_id (Optional[str|int]): 消息id(必需)
            raw (Optional[dict]): 原始请求体

        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "self_id": 0,
                "user_id": 0,
                "time": 0,
                "message_id": 0,
                "message_seq": 0,
                "real_id": 0,
                "real_seq": "string",
                "message_type": "string",
                "sender": {
                    "user_id": 0,
                    "nickname": "string",
                    "sex": "male",
                    "age": 0,
                    "card": "string",
                    "role": "owner"
                },
                "raw_message": "string",
                "font": 0,
                "sub_type": "string",
                "message": [
                    {
                        "type": "text",
                        "data": {
                            "text": "string"
                        }
                    }
                ],
                "message_format": "string",
                "post_type": "string",
                "group_id": 0
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }        
        '''
        GET_FORWARD_MSG = "napcat_get_forward_msg"  
        '''获取合并转发消息
        
        Args:
            message_id (Optional[str|int]): 消息id(必需)
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "messages": [
                    {
                        "self_id": 0,
                        "user_id": 0,
                        "time": 0,
                        "message_id": 0,
                        "message_seq": 0,
                        "real_id": 0,
                        "real_seq": "string",
                        "message_type": "string",
                        "sender": {
                            "user_id": 0,
                            "nickname": "string",
                            "sex": "male",
                            "age": 0,
                            "card": "string",
                            "role": "owner"
                        },
                        "raw_message": "string",
                        "font": 0,
                        "sub_type": "string",
                        "message": [
                            {
                                "type": "text",
                                "data": {
                                    "text": "string"
                                }
                            }
                        ],
                        "message_format": "string",
                        "post_type": "string",
                        "group_id": 0
                    }
                ]
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SET_MSG_EMOJI_LIKE = "napcat_set_msg_emoji_like"    
        '''贴表情
        
        Args:
            message_id (Optional[str|int]): 消息id(必需)
            emoji_id (Optional[int]): 表情id(必需)
            set (Optional[bool]): 是否贴(必需)
            raw (Optional[dict]): 原始请求体

        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "result": 0,
                "errMsg": "string"
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        GET_FRIEND_MSG_HISTORY = "napcat_get_friend_msg_history"    
        '''获取好友历史消息
        
        Args:
            user_id (Optional[str|int]): 用户id(必需)
            message_seq (Optional[str|int]): 消息序号,0为最新
            count (Optional[int]): 获取数量
            reverseOrder (Optional[bool]): 是否倒序
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "messages": [
                    {
                        "self_id": 0,
                        "user_id": 0,
                        "time": 0,
                        "message_id": 0,
                        "message_seq": 0,
                        "real_id": 0,
                        "real_seq": "string",
                        "message_type": "string",
                        "sender": {
                            "user_id": 0,
                            "nickname": "string",
                            "sex": "male",
                            "age": 0,
                            "card": "string",
                            "role": "owner"
                        },
                        "raw_message": "string",
                        "font": 0,
                        "sub_type": "string",
                        "message": [
                            {
                                "type": "text",
                                "data": {
                                    "text": "string"
                                }
                            }
                        ],
                        "message_format": "string",
                        "post_type": "string",
                        "group_id": 0
                    }
                ]
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        FETCH_EMOJI_LIKE = "napcat_fetch_emoji_like"    
        '''获取贴表情详情
        
        Args:
            message_id (Optional[str|int]): 消息id(必需)
            emojiId (Optional[str]): 表情id(必需)
            emojiType (Optional[str]): 表情类型(必需)
            count (Optional[int]): 返回数量
            raw (Optional[dict]): 原始请求体
        
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "result": 0,
                "errMsg": "string",
                "emojiLikesList": [
                    {
                        "tinyId": "string",
                        "nickName": "string",
                        "headUrl": "string"
                    }
                ],
                "cookie": "string",
                "isLastPage": true,
                "isFirstPage": true
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SEND_FORWARF_MSG = "napcat_send_forward_msg"    
        '''发送合并转发消息
        
        Args:
            group_id (Optional[str|int]): 群号
            user_id (Optional[str|int]): 用户id
            messages (Optional[dict]): 一级合并转发消息节点(必需)
            news (Optional[dict]): 原转发消息之外的消息(必需)
            prompt (Optional[str]): 外显(必需)
            summary (Optional[str]): 底下文本(必需)
            source (Optional[str]): 内容(必需)
            raw (Optional[dict]): 原始请求体
            
        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {},
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''
        SEND_GROUP_AI_RECORD = "napcat_send_group_ai_record"    
        '''发送群AI语音
        
        Args:
            group_id (Optional[str|int]): 群号(必需)
            character (Optional[str]): 角色id(必需)
            text (Optional[str]): 文本(必需)
            raw (Optional[dict]): 原始请求体

        Returns:
            dict: {
            "status": "ok",
            "retcode": 0,
            "data": {
                "message_id": "string"
            },
            "message": "string",
            "wording": "string",
            "echo": "string"
        }
        '''

    class GROUP(Enum):
        """
        该分类是对群聊相关的操作，只能由外部触发，napcat_plugin负责处理
        """
        SET_GROUP_SEARCH = "napcat_set_group_search"
        '''设置群搜索'''
        GET_GROUP_DETAIL_INFO = "napcat_get_group_detail_info"  
        '''获取群详细信息'''
        SET_GROUP_ADD_OPTION = "napcat_set_group_add_option"    
        '''设置群添加选项'''
        SET_GROUP_ROBOT_ADD_OPTION = "napcat_set_group_robot_add_option"    
        '''设置群机器人添加选项'''
        SET_GROUP_KICK_MEMBERS = "napcat_set_group_kick_members"    
        '''批量踢出群成员'''
        SET_GROUP_KICK = "napcat_set_group_kick"    
        '''群踢人'''
        GET_GROUP_SYSTEM_MSG = "napcat_get_group_system_msg"    
        '''获取群系统消息'''
        SET_GROUP_BAN = "napcat_set_group_ban"  
        '''群禁言'''
        GET_ESSENCE_MSG_LIST = "napcat_get_essence_msg_list"    
        '''获取群精华消息'''
        SET_GROUP_WHOLE_BAN = "napcat_set_group_whole_ban"  
        '''全体禁言'''
        SET_GROUP_PORTRAINT = "napcat_set_group_portrait"   
        '''设置群头像'''
        SET_GROUP_ADMIN = "napcat_set_group_admin"  
        '''设置群管理'''
        SET_GROUP_CARD = "napcat_group_card"    
        '''设置群成员名片'''
        SET_ESSENCE_MSG = "napcat_set_essence_msg"  
        '''设置群精华消息'''
        SET_GROUP_NAME = "napcat_set_group_name"    
        '''设置群名'''
        DELETE_ESSENCE_MSG = "napcat_delete_essence_msg"    
        '''删除群精华消息'''
        SET_GROUP_LEAVE = "napcat_set_group_leave"  
        '''退群'''
        SEND_GROUP_NOTICE = "napcat_group_notice"   
        '''发送群公告'''
        SET_GROUP_SPECIAL_TITLE = "napcat_set_group_special_title"  
        '''设置群头衔'''
        GET_GROUP_NOTICE = "napcat_get_group_notice"    
        '''获取群公告'''
        SET_GROUP_ADD_REQUEST = "napcat_set_group_add_request"  
        '''处理加群请求'''
        GET_GROUP_INFO = "napcat_get_group_info"    
        '''获取群信息'''
        GET_GROUP_LIST = "napcat_get_group_list"    
        '''获取群列表'''
        DELETE_GROUP_NOTICE = "napcat_del_group_notice"
        '''删除群公告'''
        GET_GROUP_MEMBER_INFO = "napcat_get_group_member_info"
        '''获取群成员信息'''
        GET_GROUP_MEMBER_LIST = "napcat_get_group_member_list"
        '''获取群成员列表'''
        GET_GROUP_HONOR_INFO = "napcat_get_group_honor_info"
        '''获取群荣誉'''
        GET_GROUP_INFO_EX = "napcat_get_group_info_ex"
        '''获取群信息ex'''   
        GET_GROUP_AT_ALL_REMAIN = "napcat_get_group_at_all_remain"
        '''获取群 @全体成员 剩余次数'''
        GET_GROUP_SHUT_LIST = "napcat_get_group_shut_list"
        '''获取群禁言列表'''
        GET_GROUP_IGNORED_NOTIFIES = "napcat_get_group_ignored_notifies"
        '''获取群过滤系统消息'''
        SET_GROUP_SIGN = "napcat_set_group_sign"
        '''群打卡'''


