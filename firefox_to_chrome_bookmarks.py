#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Firefox 书签迁移到 Chrome 脚本
功能：将本地的 Firefox 书签完整迁移到 Chrome 中，不生成新的文件夹并且书签栏显示一致
"""

import os
import sqlite3
import json
import shutil
from datetime import datetime
from pathlib import Path


def get_firefox_profile_path():
    """
    获取 Firefox 默认配置文件路径
    """
    if os.name == 'nt':  # Windows
        appdata = os.environ.get('APPDATA', '')
        firefox_profiles_path = os.path.join(appdata, 'Mozilla', 'Firefox', 'Profiles')
    else:  # macOS/Linux
        home = os.path.expanduser('~')
        if os.name == 'posix':
            if 'darwin' in os.sys.platform:  # macOS
                firefox_profiles_path = os.path.join(home, 'Library', 'Application Support', 'Firefox', 'Profiles')
            else:  # Linux
                firefox_profiles_path = os.path.join(home, '.mozilla', 'firefox')
        else:
            raise Exception("不支持的操作系统")
    
    if not os.path.exists(firefox_profiles_path):
        raise Exception(f"Firefox 配置文件路径不存在: {firefox_profiles_path}")
    
    # 查找默认配置文件（通常以 .default-release 结尾）
    profiles = [d for d in os.listdir(firefox_profiles_path) if os.path.isdir(os.path.join(firefox_profiles_path, d))]
    
    # 优先选择 .default-release 结尾的配置文件
    default_profiles = [p for p in profiles if p.endswith('.default-release')]
    if default_profiles:
        return os.path.join(firefox_profiles_path, default_profiles[0])
    
    # 如果没有 .default-release，选择 .default 结尾的
    default_profiles = [p for p in profiles if p.endswith('.default')]
    if default_profiles:
        return os.path.join(firefox_profiles_path, default_profiles[0])
    
    # 如果都没有，返回第一个配置文件
    if profiles:
        return os.path.join(firefox_profiles_path, profiles[0])
    
    raise Exception("未找到 Firefox 配置文件")


def get_chrome_bookmarks_path():
    """
    获取 Chrome 书签文件路径
    """
    if os.name == 'nt':  # Windows
        localappdata = os.environ.get('LOCALAPPDATA', '')
        chrome_bookmarks_path = os.path.join(localappdata, 'Google', 'Chrome', 'User Data', 'Default', 'Bookmarks')
    else:  # macOS/Linux
        home = os.path.expanduser('~')
        if os.name == 'posix':
            if 'darwin' in os.sys.platform:  # macOS
                chrome_bookmarks_path = os.path.join(home, 'Library', 'Application Support', 'Google', 'Chrome', 'Default', 'Bookmarks')
            else:  # Linux
                chrome_bookmarks_path = os.path.join(home, '.config', 'google-chrome', 'Default', 'Bookmarks')
        else:
            raise Exception("不支持的操作系统")
    
    return chrome_bookmarks_path


def extract_firefox_bookmarks(places_db_path):
    """
    从 Firefox 的 places.sqlite 数据库中提取书签
    返回一个字典，包含书签栏、其他书签等分类
    """
    if not os.path.exists(places_db_path):
        raise Exception(f"Firefox 书签数据库不存在: {places_db_path}")
    
    conn = sqlite3.connect(places_db_path)
    cursor = conn.cursor()
    
    # Firefox 书签的特殊文件夹 ID
    # 1: 根节点
    # 2: 书签栏 (Bookmarks Toolbar)
    # 3: 书签菜单 (Bookmarks Menu)
    # 4: 未排序书签 (Unsorted Bookmarks)
    # 5: 移动设备书签 (Mobile Bookmarks)
    
    # 首先获取所有书签的基本信息
    cursor.execute("""
        SELECT 
            b.id, 
            b.parent, 
            b.type, 
            b.fk, 
            b.title, 
            b.position,
            b.dateAdded,
            b.lastModified,
            p.url
        FROM moz_bookmarks b
        LEFT JOIN moz_places p ON b.fk = p.id
        ORDER BY b.parent, b.position
    """)
    
    bookmarks = cursor.fetchall()
    conn.close()
    
    # 构建书签树
    bookmark_tree = {}
    for bookmark in bookmarks:
        bookmark_id, parent, bookmark_type, fk, title, position, date_added, last_modified, url = bookmark
        
        if bookmark_id not in bookmark_tree:
            bookmark_tree[bookmark_id] = {
                'id': bookmark_id,
                'parent': parent,
                'type': bookmark_type,
                'fk': fk,
                'title': title,
                'position': position,
                'dateAdded': date_added,
                'lastModified': last_modified,
                'url': url,
                'children': []
            }
    
    # 构建父子关系
    for bookmark_id, bookmark in bookmark_tree.items():
        parent_id = bookmark['parent']
        if parent_id in bookmark_tree and parent_id != bookmark_id:
            bookmark_tree[parent_id]['children'].append(bookmark)
    
    # 按位置排序子节点
    for bookmark_id, bookmark in bookmark_tree.items():
        bookmark['children'].sort(key=lambda x: x['position'])
    
    return bookmark_tree


def convert_firefox_to_chrome(firefox_bookmark_tree, next_chrome_id=1):
    """
    将 Firefox 书签树转换为 Chrome 格式
    Firefox 特殊文件夹 ID:
    - 1: 根节点
    - 2: 书签栏 (Bookmarks Toolbar) -> Chrome 的 bookmark_bar
    - 3: 书签菜单 (Bookmarks Menu) -> Chrome 的 other
    - 4: 未排序书签 (Unsorted Bookmarks) -> Chrome 的 other
    - 5: 移动设备书签 (Mobile Bookmarks) -> Chrome 的 synced
    """
    chrome_roots = {
        'bookmark_bar': {
            'children': [],
            'name': '书签栏',
            'type': 'folder'
        },
        'other': {
            'children': [],
            'name': '其他书签',
            'type': 'folder'
        },
        'synced': {
            'children': [],
            'name': '移动设备书签',
            'type': 'folder'
        }
    }
    
    current_id = next_chrome_id
    
    def convert_node(firefox_node, parent_id):
        nonlocal current_id
        
        chrome_node = {}
        
        # Firefox 类型: 1=书签, 2=文件夹
        if firefox_node['type'] == 2:  # 文件夹
            chrome_node['type'] = 'folder'
            chrome_node['name'] = firefox_node['title'] if firefox_node['title'] else '未命名文件夹'
            chrome_node['children'] = []
            
            # 转换子节点
            for child in firefox_node['children']:
                child_node = convert_node(child, current_id)
                if child_node:
                    chrome_node['children'].append(child_node)
        else:  # 书签
            if not firefox_node['url']:
                return None
            
            chrome_node['type'] = 'url'
            chrome_node['name'] = firefox_node['title'] if firefox_node['title'] else firefox_node['url']
            chrome_node['url'] = firefox_node['url']
        
        # 设置 ID 和元数据
        chrome_node['id'] = str(current_id)
        current_id += 1
        
        # 转换时间戳 (Firefox 使用微秒，Chrome 使用 1601-01-01 以来的微秒)
        # Firefox 的 dateAdded 是从 1970-01-01 开始的微秒
        # Chrome 的 date_added 是从 1601-01-01 开始的微秒
        # 1601-01-01 到 1970-01-01 的秒数: 11644473600
        firefox_epoch = 11644473600 * 1000000  # 微秒
        
        if firefox_node['dateAdded']:
            chrome_node['date_added'] = str(firefox_node['dateAdded'] + firefox_epoch)
        else:
            chrome_node['date_added'] = str(int(datetime.now().timestamp() * 1000000) + firefox_epoch)
        
        if firefox_node['lastModified']:
            chrome_node['date_modified'] = str(firefox_node['lastModified'] + firefox_epoch)
        
        chrome_node['meta_info'] = {'last_visited_desktop': '0'}
        
        return chrome_node
    
    # 处理 Firefox 的特殊文件夹
    # 2: 书签栏 -> Chrome 的 bookmark_bar
    if 2 in firefox_bookmark_tree:
        toolbar_bookmarks = firefox_bookmark_tree[2]
        for child in toolbar_bookmarks['children']:
            child_node = convert_node(child, 0)
            if child_node:
                chrome_roots['bookmark_bar']['children'].append(child_node)
    
    # 3: 书签菜单 -> Chrome 的 other
    if 3 in firefox_bookmark_tree:
        menu_bookmarks = firefox_bookmark_tree[3]
        for child in menu_bookmarks['children']:
            child_node = convert_node(child, 0)
            if child_node:
                chrome_roots['other']['children'].append(child_node)
    
    # 4: 未排序书签 -> Chrome 的 other
    if 4 in firefox_bookmark_tree:
        unsorted_bookmarks = firefox_bookmark_tree[4]
        for child in unsorted_bookmarks['children']:
            child_node = convert_node(child, 0)
            if child_node:
                chrome_roots['other']['children'].append(child_node)
    
    # 5: 移动设备书签 -> Chrome 的 synced
    if 5 in firefox_bookmark_tree:
        mobile_bookmarks = firefox_bookmark_tree[5]
        for child in mobile_bookmarks['children']:
            child_node = convert_node(child, 0)
            if child_node:
                chrome_roots['synced']['children'].append(child_node)
    
    # 设置根文件夹的 ID
    # 通常 Chrome 的 bookmark_bar id 是 1, other 是 2, synced 是 3
    # 但我们需要根据实际情况调整
    def set_root_ids(roots):
        nonlocal current_id
        # 先收集所有需要设置 ID 的节点
        all_nodes = []
        
        def collect_nodes(node):
            all_nodes.append(node)
            if 'children' in node:
                for child in node['children']:
                    collect_nodes(child)
        
        for root_name, root_node in roots.items():
            collect_nodes(root_node)
        
        # 重新分配 ID
        for i, node in enumerate(all_nodes):
            node['id'] = str(i + 1)
        
        # 更新 current_id
        current_id = len(all_nodes) + 1
    
    set_root_ids(chrome_roots)
    
    return chrome_roots, current_id


def backup_chrome_bookmarks(chrome_bookmarks_path):
    """
    备份 Chrome 书签文件
    """
    if not os.path.exists(chrome_bookmarks_path):
        return None
    
    # 创建备份文件名，包含时间戳
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = f"{chrome_bookmarks_path}.backup_{timestamp}"
    
    # 复制文件
    shutil.copy2(chrome_bookmarks_path, backup_path)
    
    return backup_path


def write_chrome_bookmarks(chrome_bookmarks_path, chrome_roots):
    """
    将书签写入 Chrome 的 Bookmarks 文件
    """
    # 构建完整的 Chrome 书签结构
    chrome_bookmarks = {
        'checksum': '',
        'roots': chrome_roots,
        'version': 1
    }
    
    # 写入文件
    with open(chrome_bookmarks_path, 'w', encoding='utf-8') as f:
        json.dump(chrome_bookmarks, f, ensure_ascii=False, indent=2)


def main():
    """
    主函数
    """
    print("=" * 60)
    print("Firefox 书签迁移到 Chrome 工具")
    print("=" * 60)
    
    try:
        # 获取 Firefox 配置文件路径
        print("\n[1/5] 查找 Firefox 配置文件...")
        firefox_profile_path = get_firefox_profile_path()
        print(f"    找到 Firefox 配置文件: {firefox_profile_path}")
        
        # 获取 places.sqlite 路径
        places_db_path = os.path.join(firefox_profile_path, 'places.sqlite')
        if not os.path.exists(places_db_path):
            raise Exception(f"Firefox 书签数据库不存在: {places_db_path}")
        print(f"    找到书签数据库: {places_db_path}")
        
        # 提取 Firefox 书签
        print("\n[2/5] 提取 Firefox 书签...")
        firefox_bookmark_tree = extract_firefox_bookmarks(places_db_path)
        print(f"    成功提取书签树结构")
        
        # 获取 Chrome 书签路径
        print("\n[3/5] 查找 Chrome 书签文件...")
        chrome_bookmarks_path = get_chrome_bookmarks_path()
        print(f"    Chrome 书签文件路径: {chrome_bookmarks_path}")
        
        # 备份 Chrome 书签
        print("\n[4/5] 备份 Chrome 现有书签...")
        if os.path.exists(chrome_bookmarks_path):
            backup_path = backup_chrome_bookmarks(chrome_bookmarks_path)
            print(f"    已备份到: {backup_path}")
        else:
            print("    Chrome 书签文件不存在，将创建新文件")
        
        # 读取现有 Chrome 书签（如果存在）以获取下一个 ID
        next_chrome_id = 1
        if os.path.exists(chrome_bookmarks_path):
            try:
                with open(chrome_bookmarks_path, 'r', encoding='utf-8') as f:
                    existing_bookmarks = json.load(f)
                    # 查找最大的 ID
                    max_id = 0
                    
                    def find_max_id(node):
                        nonlocal max_id
                        if 'id' in node:
                            try:
                                node_id = int(node['id'])
                                if node_id > max_id:
                                    max_id = node_id
                            except:
                                pass
                        if 'children' in node:
                            for child in node['children']:
                                find_max_id(child)
                    
                    if 'roots' in existing_bookmarks:
                        for root_name, root_node in existing_bookmarks['roots'].items():
                            find_max_id(root_node)
                    
                    next_chrome_id = max_id + 1
                    print(f"    现有 Chrome 书签最大 ID: {max_id}")
            except Exception as e:
                print(f"    读取现有 Chrome 书签失败: {e}")
        
        # 转换书签格式
        print("\n[5/5] 转换并写入书签...")
        chrome_roots, _ = convert_firefox_to_chrome(firefox_bookmark_tree, next_chrome_id)
        
        # 写入 Chrome 书签文件
        write_chrome_bookmarks(chrome_bookmarks_path, chrome_roots)
        print(f"    书签已成功写入: {chrome_bookmarks_path}")
        
        print("\n" + "=" * 60)
        print("迁移完成！")
        print("=" * 60)
        print("\n注意事项:")
        print("1. 请确保 Chrome 浏览器已关闭，否则更改可能不会生效")
        print("2. 重新打开 Chrome 后，书签应该已经更新")
        print("3. 如果出现问题，可以使用备份文件恢复")
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
