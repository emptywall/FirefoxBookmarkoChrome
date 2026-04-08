#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本：查看 Firefox 书签数据库结构
"""

import os
import sqlite3
import shutil
import tempfile
from datetime import datetime


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
    
    # 查找所有配置文件目录
    profiles = [d for d in os.listdir(firefox_profiles_path) if os.path.isdir(os.path.join(firefox_profiles_path, d))]
    
    if not profiles:
        raise Exception("未找到 Firefox 配置文件目录")
    
    # 筛选出包含 places.sqlite 文件的配置文件
    valid_profiles = []
    for profile in profiles:
        profile_path = os.path.join(firefox_profiles_path, profile)
        places_db_path = os.path.join(profile_path, 'places.sqlite')
        if os.path.exists(places_db_path):
            # 获取 places.sqlite 的修改时间
            mtime = os.path.getmtime(places_db_path)
            valid_profiles.append((profile_path, mtime))
    
    if not valid_profiles:
        raise Exception("未找到包含书签数据库的 Firefox 配置文件")
    
    # 按修改时间排序，选择最新的配置文件
    valid_profiles.sort(key=lambda x: x[1], reverse=True)
    return valid_profiles[0][0]


def debug_bookmarks():
    """
    调试 Firefox 书签结构
    """
    print("=" * 60)
    print("Firefox 书签结构调试工具")
    print("=" * 60)
    
    # 获取 Firefox 配置文件路径
    print("\n[1/4] 查找 Firefox 配置文件...")
    firefox_profile_path = get_firefox_profile_path()
    print(f"    找到 Firefox 配置文件: {firefox_profile_path}")
    
    # 获取 places.sqlite 路径
    places_db_path = os.path.join(firefox_profile_path, 'places.sqlite')
    if not os.path.exists(places_db_path):
        raise Exception(f"Firefox 书签数据库不存在: {places_db_path}")
    print(f"    找到书签数据库: {places_db_path}")
    
    # 复制数据库文件到临时位置
    print("\n[2/4] 复制数据库到临时位置...")
    temp_dir = tempfile.gettempdir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_db_path = os.path.join(temp_dir, f'firefox_places_debug_{timestamp}.sqlite')
    
    try:
        shutil.copy2(places_db_path, temp_db_path)
        print(f"    已复制数据库到临时文件: {temp_db_path}")
    except Exception as e:
        raise Exception(f"无法复制 Firefox 书签数据库。请确保 Firefox 浏览器已关闭，然后重试。\n错误详情: {e}")
    
    # 连接数据库
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()
    
    # 查看 moz_bookmarks_roots 表
    print("\n[3/4] 查看 moz_bookmarks_roots 表...")
    try:
        cursor.execute("SELECT * FROM moz_bookmarks_roots")
        roots = cursor.fetchall()
        print(f"    moz_bookmarks_roots 表包含 {len(roots)} 条记录:")
        for root in roots:
            print(f"        {root}")
    except Exception as e:
        print(f"    无法读取 moz_bookmarks_roots 表: {e}")
    
    # 查看 moz_bookmarks 表中的前 20 条记录
    print("\n[4/4] 查看 moz_bookmarks 表中的特殊文件夹...")
    cursor.execute("""
        SELECT 
            id, 
            parent, 
            type, 
            fk, 
            title, 
            position
        FROM moz_bookmarks
        WHERE id <= 10
        ORDER BY id
    """)
    special_folders = cursor.fetchall()
    print(f"    ID 1-10 的记录:")
    print(f"    {'ID':<5} {'Parent':<8} {'Type':<6} {'FK':<8} {'Title':<20} {'Position':<8}")
    print(f"    {'-'*5} {'-'*8} {'-'*6} {'-'*8} {'-'*20} {'-'*8}")
    for folder in special_folders:
        id_, parent, type_, fk, title, position = folder
        title_str = str(title) if title else 'NULL'
        fk_str = str(fk) if fk else 'NULL'
        print(f"    {id_:<5} {parent:<8} {type_:<6} {fk_str:<8} {title_str:<20} {position:<8}")
    
    # 查看书签栏 (ID 2) 的子节点
    print("\n" + "=" * 60)
    print("书签栏 (ID 2) 的内容:")
    print("=" * 60)
    cursor.execute("""
        SELECT 
            b.id, 
            b.parent, 
            b.type, 
            b.title, 
            p.url
        FROM moz_bookmarks b
        LEFT JOIN moz_places p ON b.fk = p.id
        WHERE b.parent = 2
        ORDER BY b.position
    """)
    toolbar_bookmarks = cursor.fetchall()
    print(f"    共 {len(toolbar_bookmarks)} 个项目:")
    print(f"    {'ID':<5} {'Type':<8} {'Title':<30} {'URL'}")
    print(f"    {'-'*5} {'-'*8} {'-'*30} {'-'*40}")
    for bookmark in toolbar_bookmarks:
        id_, parent, type_, title, url = bookmark
        type_str = '文件夹' if type_ == 2 else '书签'
        title_str = str(title) if title else '无标题'
        url_str = str(url) if url else 'N/A'
        print(f"    {id_:<5} {type_str:<8} {title_str[:30]:<30} {url_str[:40]}")
    
    # 查看书签菜单 (ID 3) 的子节点数量
    cursor.execute("SELECT COUNT(*) FROM moz_bookmarks WHERE parent = 3")
    menu_count = cursor.fetchone()[0]
    print(f"\n书签菜单 (ID 3) 包含 {menu_count} 个项目")
    
    # 查看未排序书签 (ID 4) 的子节点数量
    cursor.execute("SELECT COUNT(*) FROM moz_bookmarks WHERE parent = 4")
    unsorted_count = cursor.fetchone()[0]
    print(f"未排序书签 (ID 4) 包含 {unsorted_count} 个项目")
    
    # 查看移动设备书签 (ID 5) 的子节点数量
    cursor.execute("SELECT COUNT(*) FROM moz_bookmarks WHERE parent = 5")
    mobile_count = cursor.fetchone()[0]
    print(f"移动设备书签 (ID 5) 包含 {mobile_count} 个项目")
    
    # 关闭数据库连接
    conn.close()
    
    # 清理临时文件
    try:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
            print(f"\n已清理临时数据库文件: {temp_db_path}")
    except Exception as e:
        print(f"\n警告: 清理临时文件失败: {e}")
    
    print("\n" + "=" * 60)
    print("调试完成！")
    print("=" * 60)


if __name__ == '__main__':
    try:
        debug_bookmarks()
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
