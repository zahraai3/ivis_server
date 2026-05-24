# هذا الملف يحتوي على الحالة المشتركة للنظام بين عدة Threads

import threading

# Lock يستخدم لمنع تعارض الوصول للـ state بين أكثر من Thread
lock = threading.Lock()

# قاموس الحالة الرئيسي للنظام
# يحتوي على جميع القيم التي يتم قراءتها وتحديثها أثناء التشغيل
state = {
    "setup_done":        False,   # هل تم الانتهاء من الإعداد الأولي للنظام
    "running":           False,   # هل النظام يعمل حالياً

    "percent":           0.0,     # نسبة الإنجاز (0 - 100)
    "current_volume":    0.0,     # الحجم الحالي المنفذ
    "current_flow_rate": 0.0,     # معدل التدفق الفعلي
    "required_flow_rate":0.0,     # معدل التدفق المطلوب

    "deviation":         0.0,     # الفرق بين المطلوب والفعلي

    "remaining_time":    "Calculating...",  # الوقت المتبقي للعملية

    "occlusion":         False,   # حالة انسداد في الأنبوب
    "leak":              False,   # حالة وجود تسريب

    "alarm10_active":    False,   # تفعيل الإنذار رقم 10
    "alarm10_ack":       False,   # تأكيد/إقرار المستخدم بالإنذار

    "fluid_name":        "",      # اسم السائل المستخدم
    "capacity_ml":       0,       # السعة الكلية (ml)
    "room":              "",      # موقع الجهاز أو الغرفة
}

# متغير مؤقت لتخزين إعدادات لم يتم اعتمادها بعد
pending_setup = None

# Event يستخدم لتنسيق بدء الإعداد بين Threads المختلفة
# يتم الانتظار عليه حتى يتم تفعيل الإعداد بالكامل
setup_event = threading.Event()